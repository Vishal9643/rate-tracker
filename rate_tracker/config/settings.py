"""
Django settings for Rate-Tracker project.
All secrets loaded from env vars — fail fast if missing.
"""
import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured

# Load .env automatically for local development (no-op if already set or file missing)
try:
    from dotenv import load_dotenv
    _base = Path(__file__).resolve().parent.parent
    load_dotenv(dotenv_path=_base / '.env', override=False)
    # .env.local overrides .env for local dev without Docker
    load_dotenv(dotenv_path=_base / '.env.local', override=True)
except ImportError:
    pass  # python-dotenv not installed — rely on env being set externally (Docker, CI, etc.)

BASE_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Fail-fast env var loader
# ---------------------------------------------------------------------------
def require_env(name: str) -> str:
    """Raise ImproperlyConfigured immediately if a required env var is absent."""
    value = os.environ.get(name, '').strip()
    if not value:
        raise ImproperlyConfigured(
            f"Required environment variable '{name}' is not set. "
            f"Copy .env.example to .env and fill in all required values."
        )
    return value


def get_env(name: str, default: str = '') -> str:
    return os.environ.get(name, default)


# ---------------------------------------------------------------------------
# Core settings
# ---------------------------------------------------------------------------
SECRET_KEY = get_env('DJANGO_SECRET_KEY', 'dev-secret-key-change-in-production')
DEBUG = get_env('DJANGO_DEBUG', 'True').lower() == 'true'
ALLOWED_HOSTS = get_env('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third-party
    'rest_framework',
    'django_celery_beat',
    # Local
    'rates',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'rates.middleware.SlowQueryMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# ---------------------------------------------------------------------------
# Database — PostgreSQL
# ---------------------------------------------------------------------------
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3' if not get_env('POSTGRES_DB') else 'django.db.backends.postgresql',
        'NAME': get_env('POSTGRES_DB') if get_env('POSTGRES_DB') else BASE_DIR / 'db.sqlite3',
        'USER': get_env('POSTGRES_USER', 'postgres'),
        'PASSWORD': get_env('POSTGRES_PASSWORD', 'postgres'),
        'HOST': get_env('POSTGRES_HOST', 'localhost'),
        'PORT': get_env('POSTGRES_PORT', '5432'),
        'CONN_MAX_AGE': 60,
    }
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ---------------------------------------------------------------------------
# Cache — Redis via django-redis
# ---------------------------------------------------------------------------
REDIS_URL = get_env('REDIS_URL', '')

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache' if not get_env('REDIS_URL') else 'django_redis.cache.RedisCache',
        'LOCATION': REDIS_URL,
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'SOCKET_CONNECT_TIMEOUT': 5,
            'SOCKET_TIMEOUT': 5,
            'IGNORE_EXCEPTIONS': False,
        },
        'KEY_PREFIX': 'rate_tracker',
    }
}

# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = get_env('CELERY_BROKER_URL', 'redis://localhost:6379/1')
CELERY_RESULT_BACKEND = get_env('CELERY_RESULT_BACKEND', 'redis://localhost:6379/2')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'

# Static beat schedule — used as initial seed; can be overridden at runtime via admin
from celery.schedules import crontab
CELERY_BEAT_SCHEDULE = {
    'ingest-rates-hourly': {
        'task': 'rates.tasks.run_scheduled_ingestion',
        'schedule': crontab(minute=0),  # every hour at :00
        'options': {'expires': 3000},   # drop if not consumed within 50 min
    },
}

# ---------------------------------------------------------------------------
# API Authentication token
# ---------------------------------------------------------------------------
API_INGEST_TOKEN = get_env('API_INGEST_TOKEN', 'dev-token-change-in-production')

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [],  # Auth set per-view
    'DEFAULT_PERMISSION_CLASSES': [],
    'DEFAULT_PAGINATION_CLASS': 'rates.pagination.RatePagination',
    'PAGE_SIZE': 50,
    'DATETIME_FORMAT': '%Y-%m-%dT%H:%M:%SZ',
    'DATETIME_INPUT_FORMATS': ['%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%dT%H:%M:%S', 'iso-8601'],
}

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Structured JSON logging
# ---------------------------------------------------------------------------
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'json': {
            '()': 'pythonjsonlogger.jsonlogger.JsonFormatter',
            'format': '%(asctime)s %(name)s %(levelname)s %(message)s',
        },
        'simple': {
            'format': '[%(levelname)s] %(name)s: %(message)s',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'json' if not DEBUG else 'simple',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
    'loggers': {
        'rates': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'celery': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
