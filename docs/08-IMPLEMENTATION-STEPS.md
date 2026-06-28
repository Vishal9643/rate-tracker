# Step-by-Step Implementation Guide for Sonnet

This is the **execution order** for implementing the Rate-Tracker project. Follow these steps sequentially. Each step references the relevant design doc.

> **CRITICAL**: Read the referenced doc section before implementing each step. The docs contain exact code, design rationale, and edge cases.

---

## Phase 0: Project Scaffolding (Do This First)

### Step 0.1: Initialize Django Project

```bash
mkdir -p rate_tracker && cd rate_tracker
python -m venv venv
source venv/bin/activate
pip install django djangorestframework psycopg2-binary redis django-redis celery pyarrow pandas pytest pytest-django
django-admin startproject config .
python manage.py startapp rates
```

### Step 0.2: Create `requirements.txt`

```
Django>=5.0,<6.0
djangorestframework>=3.15,<4.0
psycopg2-binary>=2.9
redis>=5.0
django-redis>=5.4
celery>=5.4
django-celery-beat>=2.6
pyarrow>=15.0
pandas>=2.2
pytest>=8.0
pytest-django>=4.8
gunicorn>=22.0
```

### Step 0.3: Create `.env.example`

Reference: `docs/06-DOCKER-INFRASTRUCTURE.md` → Environment Variables section.

### Step 0.4: Create `.gitignore`

```
__pycache__/
*.pyc
.env
*.egg-info/
dist/
venv/
.venv/
node_modules/
.next/
*.sqlite3
postgres_data/
```

### Step 0.5: Configure `config/settings.py`

Reference: `docs/06-DOCKER-INFRASTRUCTURE.md` → Fail-Fast Validation section.

Key settings to configure:
1. `require_env()` function for fail-fast env validation
2. `INSTALLED_APPS` — add `rest_framework`, `rates`, `django_celery_beat`
3. `DATABASES` — PostgreSQL from env vars
4. `CACHES` — Redis with `django-redis`
5. `REST_FRAMEWORK` — default pagination, datetime format
6. `CELERY_*` — broker URL, result backend from env vars
7. `API_INGEST_TOKEN` — from env var

---

## Phase 1A: Database Models & Migrations

Reference: `docs/02-DATABASE-SCHEMA.md`

### Step 1.1: Create `rates/models.py`

Implement these models in order:
1. `Provider` — with `name` (unique) and `normalized_name`
2. `IngestionJob` — job tracking with status, counts, timestamps
3. `RawResponse` — raw data storage with status, linked to IngestionJob
4. `Rate` — core table with composite unique constraint and all indexes

**Critical**: Get the `UniqueConstraint` and `Index` definitions exactly right. These are the idempotency mechanism.

### Step 1.2: Generate & Review Migration

```bash
python manage.py makemigrations rates
python manage.py migrate
```

Verify the migration creates all indexes and constraints. The migration file IS a deliverable.

---

## Phase 1B: Data Cleaning Services

Reference: `docs/03-INGESTION-PIPELINE.md` → Data Cleaning Pipeline section.

### Step 1.3: Create `rates/services/__init__.py`

### Step 1.4: Create `rates/services/data_cleaner.py`

Implement:
1. `PROVIDER_NORMALIZATION` dict — map `hsbc`, `Hsbc` → `HSBC`
2. `CURRENCY_NORMALIZATION` dict — map `usd`, `US Dollar` → `USD`
3. `normalize_provider(name: str) -> str`
4. `normalize_currency(currency: str) -> str`
5. `validate_rate_value(value, rate_type: str) -> tuple[bool, str]`
6. `validate_dates(effective_date, ingestion_ts) -> tuple[bool, str]`
7. `clean_rate_record(raw: dict) -> dict` — orchestrates all above, returns cleaned dict with `is_valid` flag

### Step 1.5: Write Data Cleaning Tests FIRST

Reference: `docs/07-TESTING-STRATEGY.md` → Data Cleaning Tests section.

Create `rates/tests/test_data_cleaner.py` with parameterized tests for all normalization and validation functions.

```bash
pytest rates/tests/test_data_cleaner.py -v
```

---

## Phase 1C: Ingestion Service & Management Command

Reference: `docs/03-INGESTION-PIPELINE.md`

### Step 1.6: Create `rates/services/ingestion.py`

Implement `run_seed_ingestion(file_path: str, batch_size: int = 10000)`:
1. Create `IngestionJob` record (status='started')
2. Open parquet file with PyArrow
3. Loop through row groups:
   a. Convert to DataFrame
   b. For each row: store `RawResponse`, clean data, validate
   c. Bulk create `Provider` objects (get_or_create)
   d. Bulk create `Rate` objects (ignore_conflicts=True)
   e. Update job progress
4. Mark job completed/failed
5. Log structured JSON at every step

### Step 1.7: Create `rates/management/commands/seed_data.py`

A thin wrapper around `run_seed_ingestion()`:
- Parse CLI arguments (`--file`, `--batch-size`, `--dry-run`)
- Call the service
- Output summary to stdout

```bash
python manage.py seed_data --file rates_seed.parquet
```

### Step 1.8: Write Ingestion Tests

Reference: `docs/07-TESTING-STRATEGY.md` → Required Test: Mock HTTP section.

Create `rates/tests/test_ingestion.py`:
- Test mock HTTP response → parsed output
- Test HTTP error handling
- Test timeout handling
- Test idempotency (running twice produces no duplicates)

---

## Phase 1D: Celery Configuration & Scheduled Execution

Reference: `docs/03-INGESTION-PIPELINE.md` → Scheduled Execution section.

### Step 1.9: Create `config/celery.py`

```python
import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
app = Celery('config')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
```

### Step 1.10: Update `config/__init__.py`

```python
from .celery import app as celery_app
__all__ = ('celery_app',)
```

### Step 1.11: Create `rates/tasks.py`

Implement `run_ingestion` Celery task with retry logic.

### Step 1.12: Configure Beat Schedule

In `config/settings.py`:
```python
CELERY_BEAT_SCHEDULE = {
    'ingest-rates-every-hour': {
        'task': 'rates.tasks.run_ingestion',
        'schedule': crontab(minute=0),
    },
}
```

---

## Phase 2A: API Views & Serializers

Reference: `docs/04-API-DESIGN.md`

### Step 2.1: Create `rates/serializers.py`

Implement:
1. `RateLatestSerializer`
2. `RateHistorySerializer`
3. `RateIngestSerializer` (with `validate_rate_value`)

### Step 2.2: Create `rates/pagination.py`

Implement `RatePagination` with max_page_size=100.

### Step 2.3: Create `rates/services/cache_manager.py`

Implement:
1. `invalidate_latest_cache()`
2. `get_or_set_latest(rate_type=None, ttl=300)`

### Step 2.4: Create `rates/views.py`

Implement:
1. `HealthCheckView` (GET `/api/v1/health/`)
2. `LatestRatesView` (GET `/api/v1/rates/latest/`)
3. `RateHistoryView` (GET `/api/v1/rates/history/`)
4. `RateIngestView` (POST `/api/v1/rates/ingest/`)

### Step 2.5: Create `rates/urls.py` and update `config/urls.py`

```python
# rates/urls.py
urlpatterns = [
    path('latest/', LatestRatesView.as_view(), name='rates-latest'),
    path('history/', RateHistoryView.as_view(), name='rates-history'),
    path('ingest/', RateIngestView.as_view(), name='rates-ingest'),
]

# config/urls.py
urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/rates/', include('rates.urls')),
    path('api/v1/health/', HealthCheckView.as_view(), name='health'),
]
```

---

## Phase 2B: Authentication

Reference: `docs/04-API-DESIGN.md` → Authentication section.

### Step 2.6: Create `rates/authentication.py`

Implement `BearerTokenAuthentication` class.

### Step 2.7: Configure DRF Settings

```python
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [],  # No global auth — set per-view
    'DEFAULT_PAGINATION_CLASS': 'rates.pagination.RatePagination',
    'PAGE_SIZE': 50,
    'DATETIME_FORMAT': '%Y-%m-%dT%H:%M:%SZ',
}
```

---

## Phase 2C: API Tests

Reference: `docs/07-TESTING-STRATEGY.md` → API Endpoint Tests section.

### Step 2.8: Create Test Files

1. `rates/tests/conftest.py` — shared fixtures
2. `rates/tests/test_api_latest.py`
3. `rates/tests/test_api_history.py`
4. `rates/tests/test_api_ingest.py`

```bash
pytest rates/tests/ -v
```

---

## Phase 3: Frontend (Next.js Dashboard)

Reference: `docs/05-FRONTEND-DESIGN.md`

### Step 3.1: Initialize Next.js

```bash
npx -y create-next-app@latest frontend --typescript --eslint --app --src-dir --no-tailwind
cd frontend
npm install swr recharts
```

### Step 3.2: Create API Client

`frontend/src/lib/api.ts`

### Step 3.3: Create Constants

`frontend/src/lib/constants.ts`

### Step 3.4: Create Components

In order:
1. `frontend/src/components/LoadingState.tsx`
2. `frontend/src/components/ErrorState.tsx`
3. `frontend/src/components/RateTable.tsx`
4. `frontend/src/components/RateChart.tsx`

### Step 3.5: Create Dashboard Page

`frontend/src/app/page.tsx` — compose RateTable + RateChart

### Step 3.6: Style Everything

`frontend/src/app/globals.css` — responsive layout, dark mode, premium design

### Step 3.7: Configure Next.js

`frontend/next.config.js` — API proxy rewrite, standalone output

---

## Phase 4: Docker & Infrastructure

Reference: `docs/06-DOCKER-INFRASTRUCTURE.md`

### Step 4.1: Create `Dockerfile` (Django)

### Step 4.2: Create `frontend/Dockerfile` (Next.js)

### Step 4.3: Create `docker-compose.yml`

All 6 services: db, redis, django, celery_worker, celery_beat, frontend.

### Step 4.4: Create `Makefile`

### Step 4.5: Create Scripts

- `scripts/wait-for-it.sh`
- `scripts/seed.sh`
- `scripts/run_tests.sh`

### Step 4.6: Test Full Stack

```bash
docker-compose up --build
# Wait for services to start
# Visit http://localhost:3000 — dashboard should load
# Visit http://localhost:8000/api/v1/health/ — should return healthy

# Seed data
docker-compose exec django python manage.py seed_data

# Run tests
docker-compose exec django pytest -v
```

---

## Phase 5: Documentation (Required Deliverables)

### Step 5.1: Write `README.md`

Must cover:
- Prerequisites (Docker, Docker Compose)
- How to run locally (`docker-compose up`)
- How to run tests
- Brief architectural rationale
- Partial completion notes (if any)

### Step 5.2: Write `DECISIONS.md`

Must cover:
1. **Assumptions** — data characteristics, env constraints, normalization choices
2. **Idempotency strategy** — composite unique constraint, `ignore_conflicts=True`, re-run safety
3. **One conscious tradeoff** — e.g., "Chose Celery Beat over cron because it runs in Docker without host access"
4. **One thing to change with more time** — e.g., "Replace polling refresh with WebSocket push via Django Channels for real-time rate updates"

### Step 5.3: Write `schema.md`

Must cover:
- Each table, its columns, types
- Indexes and why
- Tradeoffs considered

---

## Phase 6: Observability (Optional Bonus)

### Step 6.1: Configure JSON Structured Logging

```python
# config/settings.py
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'json': {
            '()': 'pythonjsonlogger.jsonlogger.JsonFormatter',
            'format': '%(asctime)s %(name)s %(levelname)s %(message)s',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'json',
        },
    },
    'loggers': {
        'rates': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
```

### Step 6.2: Add Slow Query Warning Middleware

```python
# rates/middleware.py
class SlowQueryMiddleware:
    """Warn on any request taking > 200ms."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.time()
        response = self.get_response(request)
        duration_ms = (time.time() - start) * 1000
        if duration_ms > 200:
            logger.warning(json.dumps({
                'event': 'slow_request',
                'path': request.path,
                'method': request.method,
                'duration_ms': round(duration_ms, 2),
            }))
        return response
```

---

## Verification Checklist

Before submitting, verify:

- [ ] `docker-compose up` starts all services
- [ ] `localhost:3000` shows dashboard within 2 minutes
- [ ] `localhost:8000/api/v1/health/` returns `{"status": "healthy"}`
- [ ] `python manage.py seed_data` loads ~1M rows
- [ ] Running `seed_data` twice doesn't create duplicates
- [ ] `GET /api/v1/rates/latest/` returns cached data
- [ ] `GET /api/v1/rates/history/?provider=Chase&type=30yr_fixed_mortgage` returns paginated data
- [ ] `POST /api/v1/rates/ingest/` without auth returns 401
- [ ] `POST /api/v1/rates/ingest/` with auth + valid data returns 201
- [ ] `POST /api/v1/rates/ingest/` with invalid data returns 400 with structured errors
- [ ] All tests pass: `pytest -v`
- [ ] No secrets in the repo (check `.env.example` only)
- [ ] Frontend auto-refreshes every 60 seconds
- [ ] Frontend has loading states and error states
- [ ] Frontend works at 375px width
- [ ] `README.md` exists with all required sections
- [ ] `DECISIONS.md` exists with all 4 required areas
- [ ] `schema.md` exists
- [ ] No `print()` statements (use `logging`)
