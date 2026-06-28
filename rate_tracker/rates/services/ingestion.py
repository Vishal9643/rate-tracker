"""
Core ingestion service for Rate-Tracker.

Reads rates_seed.parquet in row-group chunks, cleans data, and bulk-inserts
into PostgreSQL with idempotency via unique constraint + ignore_conflicts=True.

Multi-layer idempotency:
1. Provider: get_or_create on normalized_name — no duplicate providers
2. RawResponse: unique raw_response_id from parquet UUID — no duplicate raw records
3. Rate: UniqueConstraint(provider, rate_type, effective_date, ingestion_ts)
         + bulk_create(ignore_conflicts=True) — re-runs are safe

Running seed_data twice produces identical DB state (not double the rows).
"""
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from pathlib import Path

import pyarrow.parquet as pq
import pandas as pd

from django.db import transaction, OperationalError
from django.utils import timezone as django_tz

from rates.models import IngestionJob, RawResponse, Provider, Rate
from rates.services.data_cleaner import clean_rate_record, normalize_provider

logger = logging.getLogger('rates.ingestion')

MAX_DB_RETRIES = 3
BATCH_SIZE = 10_000  # default rows per bulk_create call


def run_seed_ingestion(
    file_path: str = 'rates_seed.parquet',
    batch_size: int = BATCH_SIZE,
    dry_run: bool = False,
) -> IngestionJob:
    """
    Main entry point for ingestion.
    Called by: management command seed_data, Celery task run_scheduled_ingestion.

    Args:
        file_path: Path to parquet file (absolute or relative to working dir)
        batch_size: Number of Rate objects per bulk_create call
        dry_run: If True, validate without writing to DB

    Returns:
        IngestionJob instance with final stats
    """
    # Create job record
    job = IngestionJob.objects.create(
        status='started',
        source_file=str(file_path),
    )

    logger.info({
        'event': 'ingestion_job_started',
        'job_id': str(job.id),
        'source_file': str(file_path),
        'dry_run': dry_run,
    })

    try:
        _run_ingestion(job, file_path, batch_size, dry_run)
    except Exception as exc:
        job.status = 'failed'
        job.error_message = str(exc)
        job.completed_at = django_tz.now()
        job.save(update_fields=['status', 'error_message', 'completed_at'])

        logger.error({
            'event': 'ingestion_job_failed',
            'job_id': str(job.id),
            'error': str(exc),
        })
        raise

    return job


def _run_ingestion(
    job: IngestionJob,
    file_path: str,
    batch_size: int,
    dry_run: bool,
) -> None:
    """Inner ingestion logic. Updates job in-place."""

    # --- Open parquet file ---
    try:
        parquet_file = pq.ParquetFile(file_path)
    except Exception as exc:
        raise RuntimeError(f"Cannot open parquet file '{file_path}': {exc}") from exc

    num_row_groups = parquet_file.metadata.num_row_groups
    total_rows = parquet_file.metadata.num_rows

    job.status = 'processing'
    job.total_rows = total_rows
    job.save(update_fields=['status', 'total_rows'])

    logger.info({
        'event': 'parquet_opened',
        'job_id': str(job.id),
        'total_rows': total_rows,
        'num_row_groups': num_row_groups,
    })

    # Pre-load provider cache to reduce DB round-trips
    provider_cache: dict[str, Provider] = {}
    for p in Provider.objects.all():
        provider_cache[p.normalized_name] = p

    total_processed = 0
    total_failed = 0
    total_skipped = 0

    # --- Process row groups ---
    for group_idx in range(num_row_groups):
        t_start = time.time()
        try:
            table = parquet_file.read_row_group(group_idx)
            df = table.to_pandas()
        except Exception as exc:
            logger.error({
                'event': 'row_group_read_failed',
                'job_id': str(job.id),
                'group_idx': group_idx,
                'error': str(exc),
            })
            continue  # Skip bad chunk, don't abort

        valid_rates, failed_count, skipped = _process_chunk(
            df, job, provider_cache, batch_size, dry_run
        )

        elapsed_ms = round((time.time() - t_start) * 1000, 2)
        total_processed += valid_rates
        total_failed += failed_count
        total_skipped += skipped

        # Persist progress after each row group
        job.processed_rows = total_processed
        job.failed_rows = total_failed
        job.skipped_rows = total_skipped
        job.save(update_fields=['processed_rows', 'failed_rows', 'skipped_rows'])

        logger.info({
            'event': 'chunk_processed',
            'job_id': str(job.id),
            'group_idx': group_idx,
            'rows_in_chunk': len(df),
            'valid_rows': valid_rates,
            'invalid_rows': failed_count,
            'duration_ms': elapsed_ms,
        })

    # --- Finalise job ---
    job.status = 'completed'
    job.completed_at = django_tz.now()
    job.processed_rows = total_processed
    job.failed_rows = total_failed
    job.skipped_rows = total_skipped
    job.save(update_fields=['status', 'completed_at', 'processed_rows', 'failed_rows', 'skipped_rows'])

    logger.info({
        'event': 'ingestion_job_completed',
        'job_id': str(job.id),
        'total_rows': total_rows,
        'processed': total_processed,
        'failed': total_failed,
        'skipped': total_skipped,
    })

    # Invalidate cached latest rates
    if not dry_run:
        try:
            from rates.services.cache_manager import invalidate_latest_cache
            invalidate_latest_cache()
        except Exception as exc:
            logger.warning({
                'event': 'cache_invalidation_failed',
                'job_id': str(job.id),
                'error': str(exc),
            })


def _process_chunk(
    df: pd.DataFrame,
    job: IngestionJob,
    provider_cache: dict,
    batch_size: int,
    dry_run: bool,
) -> tuple[int, int, int]:
    """
    Process one row-group DataFrame.
    Returns (valid_count, failed_count, skipped_count).
    """
    raw_responses_to_create: list[RawResponse] = []
    rate_objects: list[Rate] = []
    failed_count = 0

    for _, row in df.iterrows():
        raw_dict = row.to_dict()
        raw_response_id = str(raw_dict.get('raw_response_id', ''))

        cleaned = clean_rate_record(raw_dict)

        if not cleaned['is_valid']:
            failed_count += 1
            for err in cleaned['validation_errors']:
                logger.warning({
                    'event': 'invalid_record',
                    'job_id': str(job.id),
                    'raw_response_id': raw_response_id,
                    'reason': err,
                    'provider': raw_dict.get('provider'),
                    'rate_type': raw_dict.get('rate_type'),
                })
            if not dry_run:
                # Store raw response marked as failed for replay capability
                raw_responses_to_create.append(RawResponse(
                    raw_response_id=raw_response_id,
                    raw_data=_serialize_raw(raw_dict),
                    source_url=str(raw_dict.get('source_url', '')),
                    ingestion_job=job,
                    status='failed',
                    error_message='; '.join(cleaned['validation_errors']),
                ))
            continue

        # Valid record
        norm_provider_name = cleaned['normalized_provider']

        # Build Rate object (provider FK resolved below)
        if not dry_run:
            raw_responses_to_create.append(RawResponse(
                raw_response_id=raw_response_id,
                raw_data=_serialize_raw(raw_dict),
                source_url=str(raw_dict.get('source_url', '')),
                ingestion_job=job,
                status='processed',
            ))

        # Get or create provider
        if norm_provider_name not in provider_cache:
            if not dry_run:
                provider, _ = Provider.objects.get_or_create(
                    normalized_name=norm_provider_name,
                    defaults={'name': str(raw_dict.get('provider', norm_provider_name))},
                )
                provider_cache[norm_provider_name] = provider
        else:
            provider = provider_cache[norm_provider_name]

        if not dry_run:
            # Parse ingestion_ts
            ingestion_ts = raw_dict.get('ingestion_ts')
            if isinstance(ingestion_ts, pd.Timestamp):
                ingestion_ts = ingestion_ts.to_pydatetime()
            if ingestion_ts and ingestion_ts.tzinfo is None:
                ingestion_ts = ingestion_ts.replace(tzinfo=timezone.utc)

            # Parse effective_date
            effective_date = raw_dict.get('effective_date')
            if isinstance(effective_date, pd.Timestamp):
                effective_date = effective_date.date()
            elif hasattr(effective_date, 'isoformat'):
                pass  # already a date
            else:
                from datetime import date as date_type
                effective_date = date_type.fromisoformat(str(effective_date))

            rate_objects.append(Rate(
                provider=provider,
                rate_type=str(raw_dict.get('rate_type', '')),
                rate_value=cleaned['rate_value'],
                effective_date=effective_date,
                currency=cleaned['normalized_currency'],
                source_url=str(raw_dict.get('source_url', '')),
                ingestion_ts=ingestion_ts,
            ))

    if dry_run:
        return len(df) - failed_count, failed_count, 0

    # --- Bulk writes with retry ---
    # 1. RawResponses (ignore duplicates — same raw_response_id can appear on re-run)
    _bulk_create_with_retry(RawResponse, raw_responses_to_create, batch_size, ignore_conflicts=True)

    # 2. Rates (ignore_conflicts handles the idempotency constraint)
    before_count = Rate.objects.count()
    _bulk_create_with_retry(Rate, rate_objects, batch_size, ignore_conflicts=True)
    after_count = Rate.objects.count()

    actually_inserted = after_count - before_count
    skipped = len(rate_objects) - actually_inserted

    return actually_inserted, failed_count, skipped


def _bulk_create_with_retry(model, objects, batch_size, ignore_conflicts=False):
    """Bulk create with exponential backoff on transient DB errors."""
    if not objects:
        return

    for attempt in range(MAX_DB_RETRIES):
        try:
            model.objects.bulk_create(objects, batch_size=batch_size, ignore_conflicts=ignore_conflicts)
            return
        except OperationalError as exc:
            if attempt == MAX_DB_RETRIES - 1:
                raise
            wait = 2 ** attempt
            logger.warning({
                'event': 'db_retry',
                'model': model.__name__,
                'attempt': attempt + 1,
                'wait_seconds': wait,
                'error': str(exc),
            })
            time.sleep(wait)


def _serialize_raw(raw_dict: dict) -> dict:
    """Convert a pandas row dict to JSON-serializable form."""
    serializable = {}
    for k, v in raw_dict.items():
        if isinstance(v, pd.Timestamp):
            serializable[k] = v.isoformat()
        elif hasattr(v, 'isoformat'):
            serializable[k] = v.isoformat()
        elif isinstance(v, float) and (v != v):  # NaN check
            serializable[k] = None
        else:
            serializable[k] = v
    return serializable
