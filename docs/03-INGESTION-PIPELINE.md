# Data Ingestion & Cleaning Strategy

## Overview

The ingestion pipeline has three stages:
1. **Read** — Load parquet file in chunks
2. **Clean** — Normalize, validate, flag bad records
3. **Persist** — Bulk insert with idempotency

## Management Command: `seed_data`

```
python manage.py seed_data [--file PATH] [--batch-size N] [--dry-run]
```

### Implementation Details

```python
# rates/management/commands/seed_data.py

class Command(BaseCommand):
    help = 'Load rate data from parquet seed file into database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file', type=str, default='rates_seed.parquet',
            help='Path to parquet file'
        )
        parser.add_argument(
            '--batch-size', type=int, default=10000,
            help='Number of rows per batch insert'
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Validate without inserting'
        )

    def handle(self, *args, **options):
        # 1. Create IngestionJob record
        # 2. Read parquet in row-group chunks (21 groups × ~48K rows each)
        # 3. For each chunk:
        #    a. Store raw responses
        #    b. Clean & validate
        #    c. Bulk upsert to Rate table
        #    d. Update job progress
        # 4. Mark job as completed/failed
        # 5. Invalidate relevant cache keys
```

## Parquet Reading Strategy

### Why PyArrow (not Pandas directly)?
- PyArrow reads parquet natively without full pandas overhead
- Can read by row-group for memory efficiency
- Snappy decompression is built-in
- Convert to pandas DataFrame per-chunk for processing

### Chunked Reading

```python
import pyarrow.parquet as pq

parquet_file = pq.ParquetFile(file_path)
# File has 21 row groups, each ~48K rows
for i in range(parquet_file.metadata.num_row_groups):
    table = parquet_file.read_row_group(i)
    df = table.to_pandas()
    process_chunk(df)
```

**Why row-group chunking**: The file is 34MB / 1M rows. Reading everything at once is feasible but row-group processing gives us:
- Progress tracking per chunk
- Better error isolation (one bad chunk doesn't kill the job)
- Memory ceiling control

## Data Cleaning Pipeline

### Step 1: Provider Normalization

```python
PROVIDER_NORMALIZATION = {
    'hsbc': 'HSBC',
    'Hsbc': 'HSBC',
    'bank of america': 'Bank of America',
    # ... etc
}

def normalize_provider(name: str) -> str:
    """Case-insensitive provider name normalization."""
    return PROVIDER_NORMALIZATION.get(name, name.strip())
```

**Strategy**: Build a normalization map. Any provider name maps to its canonical form. Unknown providers are preserved as-is (don't silently drop data).

### Step 2: Currency Normalization

```python
CURRENCY_NORMALIZATION = {
    'usd': 'USD',
    'US Dollar': 'USD',
    'us dollar': 'USD',
}

def normalize_currency(currency: str) -> str:
    return CURRENCY_NORMALIZATION.get(currency, currency.upper().strip())
```

### Step 3: Rate Value Validation

Records with data quality issues are handled as follows:

| Issue | Count | Action | Rationale |
|-------|-------|--------|-----------|
| `rate_value` is NULL | 200 | **Skip, log warning** | Cannot store a rate without a value. Mark raw_response as `failed`. |
| `rate_value` < 0 | 15 | **Skip, log warning** | Negative interest rates are theoretically possible but values like -1.84 are clearly data errors in this context. Flag and skip. |
| `rate_value` > 20 | 15 | **Skip, log warning** | Values like 97.39% are obviously corrupt. Flag and skip. Threshold of 20% is generous for financial rates. |

```python
def validate_rate_value(value, rate_type: str) -> tuple[bool, str]:
    """Returns (is_valid, error_message)."""
    if value is None or pd.isna(value):
        return False, "rate_value is null"
    if value < 0:
        return False, f"Negative rate: {value}"
    if value > 20:
        return False, f"Rate exceeds 20% threshold: {value}"
    return True, ""
```

### Step 4: Date Validation

```python
def validate_dates(effective_date, ingestion_ts) -> tuple[bool, str]:
    """Flag records where effective_date is unreasonably far from ingestion_ts."""
    if effective_date is None:
        return False, "effective_date is null"

    # If effective_date is more than 90 days after ingestion_ts, flag it
    # (These are the 50 mismatched records)
    if ingestion_ts and (effective_date - ingestion_ts.date()).days > 90:
        return False, f"effective_date {effective_date} is >90 days after ingestion {ingestion_ts}"

    return True, ""
```

**Decision**: We still ingest these records but log a warning. They might be legitimate forward-dated rates. The raw_response preserves the original data either way.

### Step 5: Deduplication Check

The composite unique constraint `(provider, rate_type, effective_date, ingestion_ts)` handles this at the DB level. On bulk insert, use:

```python
from django.db.models import Q

# Use bulk_create with ignore_conflicts=True for idempotency
Rate.objects.bulk_create(rate_objects, batch_size=5000, ignore_conflicts=True)
```

**Why `ignore_conflicts=True`**: 
- If the same data is loaded twice, the unique constraint catches duplicates
- No error thrown, just silently skips
- Much faster than checking existence row-by-row
- The `skipped_rows` counter on IngestionJob tracks how many were duplicates

## Idempotency Strategy (Critical for DECISIONS.md)

### The Problem
The spec says: *"Explain exactly how your ingestion worker handles DB with multiple data related issues"*

### The Solution: Multi-Layer Idempotency

1. **Row-level**: Composite unique constraint `(provider_id, rate_type, effective_date, ingestion_ts)` prevents duplicate rate records. `bulk_create(ignore_conflicts=True)` makes re-runs safe.

2. **Provider-level**: `Provider.name` is unique. `get_or_create()` ensures no duplicate providers.

3. **Raw response-level**: `RawResponse.raw_response_id` is unique (comes from the UUID in the parquet). Re-ingesting the same file won't create duplicate raw responses.

4. **Job-level**: Each `seed_data` run creates a new `IngestionJob`. If the previous run failed, the new run processes everything again. Duplicates are caught by the unique constraint — no manual cleanup needed.

### Running `seed_data` Multiple Times Is Safe

```
# First run: inserts ~1M records (minus ~230 invalid)
$ python manage.py seed_data
IngestionJob abc123: 1005000 total, 999770 processed, 230 failed, 0 skipped

# Second run: all valid records already exist, skipped by unique constraint
$ python manage.py seed_data
IngestionJob def456: 1005000 total, 0 processed, 230 failed, 999770 skipped
```

## Error Handling

### Parquet Read Errors
```python
try:
    parquet_file = pq.ParquetFile(file_path)
except Exception as e:
    job.status = 'failed'
    job.error_message = f"Cannot read parquet file: {e}"
    job.save()
    raise CommandError(f"Failed to read {file_path}: {e}")
```

### Per-Chunk Error Isolation
If a single chunk fails to process, log the error, mark those raw_responses as `failed`, and continue with the next chunk. Don't let one bad batch kill the whole job.

### Database Connection Errors
Retry logic with exponential backoff for transient DB connection issues:
```python
from django.db import OperationalError
import time

MAX_RETRIES = 3
for attempt in range(MAX_RETRIES):
    try:
        Rate.objects.bulk_create(batch, ignore_conflicts=True)
        break
    except OperationalError:
        if attempt == MAX_RETRIES - 1:
            raise
        time.sleep(2 ** attempt)
```

## Structured Logging (Observability)

Every step is logged with structured JSON:

```python
import logging
import json

logger = logging.getLogger('rates.ingestion')

logger.info(json.dumps({
    'event': 'ingestion_job_started',
    'job_id': str(job.id),
    'source_file': file_path,
    'total_row_groups': parquet_file.metadata.num_row_groups,
}))

# Per-chunk logging
logger.info(json.dumps({
    'event': 'chunk_processed',
    'job_id': str(job.id),
    'chunk_index': i,
    'rows_in_chunk': len(df),
    'valid_rows': valid_count,
    'invalid_rows': invalid_count,
    'duration_ms': elapsed_ms,
}))

# Bad record logging
logger.warning(json.dumps({
    'event': 'invalid_record',
    'job_id': str(job.id),
    'raw_response_id': row['raw_response_id'],
    'reason': error_message,
    'provider': row['provider'],
    'rate_type': row['rate_type'],
}))
```

## Scheduled Execution (Celery Beat)

```python
# config/celery.py
app.conf.beat_schedule = {
    'ingest-rates-every-hour': {
        'task': 'rates.tasks.run_ingestion',
        'schedule': crontab(minute=0),  # Every hour on the hour
    },
}

# rates/tasks.py
@shared_task(bind=True, max_retries=3)
def run_ingestion(self):
    """Scheduled ingestion task — runs via Celery Beat."""
    try:
        from rates.services.ingestion import run_seed_ingestion
        run_seed_ingestion('rates_seed.parquet')
    except Exception as exc:
        logger.error(json.dumps({
            'event': 'scheduled_ingestion_failed',
            'error': str(exc),
            'retry_count': self.request.retries,
        }))
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))
```
