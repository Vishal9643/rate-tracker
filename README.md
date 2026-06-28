# Rate Tracker

A production-shaped interest-rate data pipeline — ingest, store, expose, and visualise financial rate data.

**Stack**: Django 5 · DRF · PostgreSQL 16 · Redis 7 · Celery · Next.js 14 · Docker Compose

---

## Submission

- **GitHub repo**: Submit as a **Public GitHub Repository**.
- **Screen recording**: Include a link to the video recording (including audio) where you explain your work (Loom, Google Drive, or similar). The recording should demonstrate: `docker-compose up`, seeding the DB, the dashboard at `localhost:3000`, and a live API call.
- The reviewer must be able to access the dashboard at `localhost:3000` within 2 minutes of `docker-compose up`.

---

## AI Tools Usage

This project was built with the assistance of AI coding tools.
- **Code Generation & Architecture**: AI was used to bootstrap the Django project structure, write the data cleaning algorithms, and scaffold the Next.js frontend components.
- **Debugging & Refactoring**: AI assisted in debugging SQLite-specific constraints (e.g., bypassing `DISTINCT ON`) and refining the Celery beat schedule.
- **Documentation**: AI helped format markdown documents (README, DECISIONS, schema) and generate test cases.
- **Human Oversight**: All generated code was thoroughly reviewed, tested, and modified by the developer to ensure it met production standards, architectural requirements, and idempotency constraints.

---

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) ≥ 24
- [Docker Compose](https://docs.docker.com/compose/) ≥ 2
- (Optional, for local development) Python 3.12+, Node.js 20+

## How to Run Locally

```bash
# 1. Clone the repo and enter the project
cd rate_tracker

# 2. Copy environment template (never commit .env)
cp .env.example .env
# Edit .env to set POSTGRES_PASSWORD, DJANGO_SECRET_KEY, API_INGEST_TOKEN

# 3. Start all services
docker-compose up -d --build

# 4. Wait for services to be healthy (~30 seconds)
docker-compose ps

# 5. Seed the database (~1M rows, takes 2-5 minutes)
docker-compose exec django python manage.py seed_data

# 6. Access the dashboard
open http://localhost:3000

# API is available at:
open http://localhost:8000/api/v1/health/
```

> **Note**: The dashboard at `localhost:3000` is available as soon as all services start (step 3). Seeding the database is optional — the dashboard will show empty states gracefully until data is loaded.

## How to Run Tests

```bash
# Run full test suite inside Docker
docker-compose exec django pytest -v --tb=short

# Or with coverage report
docker-compose exec django pytest --cov=rates --cov-report=term-missing

# Run locally (requires PostgreSQL running)
cd rate_tracker
source venv/bin/activate
pytest -v
```

**Key tests:**
- `test_data_cleaner.py` — 44 unit tests covering all 7 data quality issues
- `test_ingestion.py` — Required mock HTTP test + idempotency verification
- `test_api_latest.py` — GET /rates/latest/ integration tests
- `test_api_history.py` — GET /rates/history/ pagination + filter tests
- `test_api_ingest.py` — POST /rates/ingest/ auth + validation tests

## API Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/api/v1/health/` | None | Liveness + readiness check |
| `GET` | `/api/v1/rates/latest/` | None | Latest rate per provider (cached 5min) |
| `GET` | `/api/v1/rates/history/` | None | Paginated 30-day time-series |
| `POST` | `/api/v1/rates/ingest/` | Bearer token | Ingest new rate data |

**Example requests:**
```bash
# Latest rates
curl http://localhost:8000/api/v1/rates/latest/

# Filter by type
curl "http://localhost:8000/api/v1/rates/latest/?type=30yr_fixed_mortgage"

# History
curl "http://localhost:8000/api/v1/rates/history/?provider=Chase&type=30yr_fixed_mortgage"

# Ingest (replace TOKEN with your API_INGEST_TOKEN)
curl -X POST http://localhost:8000/api/v1/rates/ingest/ \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"provider":"Chase","rate_type":"30yr_fixed_mortgage","rate_value":6.75,"effective_date":"2026-03-26","currency":"USD"}'
```

## Makefile Commands

```bash
make up      # Start all services
make down    # Stop all services
make seed    # Seed database from parquet file
make test    # Run all tests
make logs    # Tail all service logs
make migrate # Run Django migrations
make shell   # Django interactive shell
make reset   # Full reset (destroys data)
```

## Architecture

```
docker-compose
├── db (PostgreSQL 16)     — primary data store
├── redis (Redis 7)        — cache + Celery broker
├── django (Django 5)      — REST API + admin
├── celery_worker          — async task processor
├── celery_beat            — hourly scheduled ingestion
└── frontend (Next.js 14)  — dashboard at :3000
```

**Key architectural choices** (full rationale in `DECISIONS.md`):
- **Celery Beat** over host cron: runs in Docker without host access, configurable at runtime
- **Composite unique constraint** for idempotency: `(provider, rate_type, effective_date, ingestion_ts)`
- **Row-group chunked parquet reading**: PyArrow reads 21 chunks of ~48K rows for memory efficiency and error isolation
- **Cache-aside pattern** with Redis: 5-minute TTL on `/rates/latest/`, invalidated on every write

## Environment Variables

Copy `.env.example` to `.env` and set:

| Variable | Required | Description |
|----------|----------|-------------|
| `POSTGRES_PASSWORD` | ✅ | PostgreSQL password |
| `DJANGO_SECRET_KEY` | ✅ | Django secret key |
| `API_INGEST_TOKEN` | ✅ | Bearer token for POST /rates/ingest/ |
| `DJANGO_DEBUG` | No | Default: `True` |
| `POSTGRES_DB` | No | Default: `rate_tracker` |

The app fails fast with a clear error if any required variable is missing — not a cryptic crash 10 minutes later.

## Deliverables

- `DECISIONS.md` — Engineering assumptions, idempotency strategy, tradeoffs
- `schema.md` — Database schema documentation with index rationale
- `rates/migrations/0001_initial.py` — Django migration (no raw SQL)
