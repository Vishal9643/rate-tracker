"""
Celery application configuration.
"""
import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('config')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# ---------------------------------------------------------------------------
# Scheduled tasks — Celery Beat
# ---------------------------------------------------------------------------
app.conf.beat_schedule = {
    'ingest-rates-every-hour': {
        'task': 'rates.tasks.run_scheduled_ingestion',
        'schedule': crontab(minute=0),  # Every hour on the hour
    },
}
