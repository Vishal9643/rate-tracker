# Architecture & Technology Choices

## Tech Stack Decision

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| Backend Framework | **Django 5.x + DRF** | Explicitly required by assessment |
| Database | **PostgreSQL 16** | Required. Best for time-series queries, JSON support, robust indexing |
| Cache | **Redis 7** | Required for API caching. Also used as Celery broker |
| Task Queue | **Celery 5.x + Redis broker** | Django-native, battle-tested for scheduled tasks |
| Scheduler | **Celery Beat** | Runs inside docker-compose, no external cron needed |
| Frontend | **Next.js 14 (App Router)** | Required for optional Phase 3 |
| Charting | **Recharts** | Lightweight, React-native, great for line charts |
| Containerization | **Docker + Docker Compose** | Required |
| Python | **3.12** | Latest stable with good library support |
| Node | **20 LTS** | Stable for Next.js |

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Docker Compose                               │
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐   │
│  │   Next.js    │───▶│  Django API  │───▶│    PostgreSQL 16     │   │
│  │  (Port 3000) │    │  (Port 8000) │    │    (Port 5432)       │   │
│  └──────────────┘    └──────┬───────┘    └──────────────────────┘   │
│                             │                       ▲               │
│                             ▼                       │               │
│                      ┌──────────────┐    ┌──────────┴───────────┐   │
│                      │    Redis     │    │   Celery Worker      │   │
│                      │  (Port 6379) │◀───│   + Celery Beat      │   │
│                      └──────────────┘    └──────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Django Project Structure

```
rate_tracker/                        # Project root
├── docker-compose.yml
├── Dockerfile                       # Django + Celery
├── Dockerfile.frontend              # Next.js
├── Makefile                         # Convenience commands
├── .env.example                     # Template for env vars
├── requirements.txt                 # Python dependencies
├── manage.py
├── rates_seed.parquet               # Seed data file
│
├── config/                          # Django project config
│   ├── __init__.py
│   ├── settings.py                  # Settings with env var validation
│   ├── urls.py
│   ├── wsgi.py
│   └── celery.py                    # Celery app configuration
│
├── rates/                           # Main Django app
│   ├── __init__.py
│   ├── models.py                    # Rate, RawResponse, IngestionJob models
│   ├── admin.py
│   ├── serializers.py               # DRF serializers
│   ├── views.py                     # API viewsets
│   ├── urls.py                      # API URL routing
│   ├── filters.py                   # DRF filter classes
│   ├── pagination.py                # Custom pagination
│   ├── authentication.py            # Bearer token auth
│   ├── permissions.py               # Custom permissions
│   ├── validators.py                # Data validation logic
│   ├── services/
│   │   ├── __init__.py
│   │   ├── ingestion.py             # Core ingestion logic
│   │   ├── data_cleaner.py          # Data normalization/cleaning
│   │   └── cache_manager.py         # Cache invalidation logic
│   ├── management/
│   │   └── commands/
│   │       └── seed_data.py         # `python manage.py seed_data`
│   ├── tasks.py                     # Celery tasks
│   ├── migrations/
│   │   └── 0001_initial.py
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py              # Shared fixtures
│       ├── test_models.py
│       ├── test_ingestion.py        # Ingestion worker tests
│       ├── test_data_cleaner.py     # Data cleaning tests
│       ├── test_api_latest.py       # GET /rates/latest tests
│       ├── test_api_history.py      # GET /rates/history tests
│       ├── test_api_ingest.py       # POST /rates/ingest tests
│       └── test_api_auth.py         # Authentication tests
│
├── frontend/                        # Next.js app
│   ├── package.json
│   ├── next.config.js
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx
│   │   │   ├── page.tsx             # Dashboard page
│   │   │   └── globals.css
│   │   ├── components/
│   │   │   ├── RateTable.tsx        # Rate comparison table
│   │   │   ├── RateChart.tsx        # 30-day history line chart
│   │   │   ├── ErrorState.tsx       # Error boundary component
│   │   │   └── LoadingState.tsx     # Loading skeleton component
│   │   ├── hooks/
│   │   │   └── useRates.ts          # Data fetching hooks with SWR
│   │   └── lib/
│   │       └── api.ts               # API client
│   └── Dockerfile
│
├── scripts/
│   ├── seed.sh                      # Seed database script
│   ├── run_tests.sh                 # Run all tests
│   └── wait-for-it.sh               # Wait for services
│
├── README.md
├── DECISIONS.md
└── schema.md
```

## Service Dependencies (Startup Order)

1. **PostgreSQL** — no dependencies
2. **Redis** — no dependencies
3. **Django (web)** — depends on PostgreSQL + Redis
4. **Celery Worker** — depends on Django + Redis + PostgreSQL
5. **Celery Beat** — depends on Redis
6. **Next.js** — depends on Django (for API)

## Key Design Decisions

### Why Celery Beat over Cron?
- Runs inside Docker natively (no host cron required)
- Shared codebase with Django
- Easy to configure intervals in Python
- Scales horizontally if needed

### Why Redis for Both Cache and Broker?
- Single infrastructure dependency
- Fast enough for both use cases at this scale
- Assessment is testing judgment about complexity budget — don't over-engineer

### Why Services Layer in Django?
- Keeps views thin (DRF views just delegate)
- Makes ingestion logic testable without HTTP
- Separates concerns: cleaning, ingestion, caching

### Why SWR in Frontend?
- Built-in 60-second auto-refresh (`refreshInterval: 60000`)
- Loading/error states handled natively
- Deduplication of requests
- Stale-while-revalidate pattern for UX
