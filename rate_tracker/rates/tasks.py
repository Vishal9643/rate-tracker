"""
Celery tasks for Rate-Tracker.

Scheduled via Celery Beat (see config/celery.py).
"""
import logging

from celery import shared_task

logger = logging.getLogger('rates.tasks')


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def run_scheduled_ingestion(self):
    """
    Scheduled ingestion task — runs via Celery Beat every hour.
    Uses the same idempotent ingestion service as the management command.
    """
    import json
    logger.info(json.dumps({
        'event': 'scheduled_ingestion_started',
        'task_id': self.request.id,
        'retry_count': self.request.retries,
    }))

    try:
        from rates.services.ingestion import run_seed_ingestion
        job = run_seed_ingestion('rates_seed.parquet')

        logger.info(json.dumps({
            'event': 'scheduled_ingestion_completed',
            'task_id': self.request.id,
            'job_id': str(job.id),
            'processed': job.processed_rows,
            'failed': job.failed_rows,
        }))

        return {
            'job_id': str(job.id),
            'status': job.status,
            'processed': job.processed_rows,
        }

    except Exception as exc:
        logger.error(json.dumps({
            'event': 'scheduled_ingestion_failed',
            'task_id': self.request.id,
            'error': str(exc),
            'retry_count': self.request.retries,
        }))
        raise self.retry(
            exc=exc,
            countdown=60 * (2 ** self.request.retries),  # 60s, 120s, 240s
        )
