# Docker & Infrastructure

## Docker Compose Services

```yaml
# docker-compose.yml
version: '3.9'

services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-rate_tracker}
      POSTGRES_USER: ${POSTGRES_USER:-postgres}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-postgres}"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

  django:
    build:
      context: .
      dockerfile: Dockerfile
    command: >
      sh -c "python manage.py migrate &&
             python manage.py runserver 0.0.0.0:8000"
    volumes:
      - .:/app
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/health/"]
      interval: 10s
      timeout: 5s
      retries: 5

  celery_worker:
    build:
      context: .
      dockerfile: Dockerfile
    command: celery -A config worker -l info --concurrency=2
    volumes:
      - .:/app
    env_file: .env
    depends_on:
      django:
        condition: service_healthy
      redis:
        condition: service_healthy

  celery_beat:
    build:
      context: .
      dockerfile: Dockerfile
    command: celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
    volumes:
      - .:/app
    env_file: .env
    depends_on:
      redis:
        condition: service_healthy

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "3000:3000"
    environment:
      - NEXT_PUBLIC_API_URL=http://django:8000
    depends_on:
      django:
        condition: service_healthy

volumes:
  postgres_data:
```

## Dockerfile (Django)

```dockerfile
# Dockerfile
FROM python:3.12-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY . .

# Create non-root user
RUN adduser --disabled-password --gecos '' appuser
USER appuser

EXPOSE 8000
```

## Dockerfile (Frontend)

```dockerfile
# frontend/Dockerfile
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV production
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

EXPOSE 3000
CMD ["node", "server.js"]
```

## Environment Variables

### `.env.example`

```bash
# === PostgreSQL ===
POSTGRES_DB=rate_tracker
POSTGRES_USER=postgres
POSTGRES_PASSWORD=changeme_in_production
POSTGRES_HOST=db
POSTGRES_PORT=5432

# === Redis ===
REDIS_URL=redis://redis:6379/0

# === Django ===
DJANGO_SECRET_KEY=changeme-generate-a-real-key-in-production
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,django

# === API Authentication ===
API_INGEST_TOKEN=changeme-generate-a-real-token

# === Celery ===
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2

# === Frontend ===
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### Fail-Fast Validation

```python
# config/settings.py (top of file)
import os

def require_env(name: str) -> str:
    """Fail fast if a required env var is missing."""
    value = os.environ.get(name)
    if not value:
        raise ImproperlyConfigured(
            f"Required environment variable '{name}' is not set. "
            f"Copy .env.example to .env and fill in all required values."
        )
    return value

# Usage:
SECRET_KEY = require_env('DJANGO_SECRET_KEY')
POSTGRES_PASSWORD = require_env('POSTGRES_PASSWORD')
API_INGEST_TOKEN = require_env('API_INGEST_TOKEN')
```

## Makefile

```makefile
# Makefile
.PHONY: up down seed test logs migrate shell

# Start all services
up:
	docker-compose up -d --build

# Stop all services
down:
	docker-compose down

# Seed the database
seed:
	docker-compose exec django python manage.py seed_data

# Run all tests
test:
	docker-compose exec django pytest -v --tb=short

# Tail all logs
logs:
	docker-compose logs -f

# Run Django migrations
migrate:
	docker-compose exec django python manage.py migrate

# Django shell
shell:
	docker-compose exec django python manage.py shell

# Full reset: stop, remove volumes, rebuild, migrate, seed
reset:
	docker-compose down -v
	docker-compose up -d --build
	sleep 10
	docker-compose exec django python manage.py migrate
	docker-compose exec django python manage.py seed_data
```

## Scripts

### `scripts/wait-for-it.sh`

Standard wait-for-it script for service dependency management in Docker.

### `scripts/seed.sh`

```bash
#!/bin/bash
set -e

echo "Waiting for database..."
python manage.py wait_for_db

echo "Running migrations..."
python manage.py migrate --noinput

echo "Seeding data..."
python manage.py seed_data

echo "Done!"
```

### `scripts/run_tests.sh`

```bash
#!/bin/bash
set -e

echo "Running Python tests..."
pytest -v --tb=short --cov=rates --cov-report=term-missing

echo ""
echo "All tests passed!"
```

## Health Check Endpoint

```python
# rates/views.py
class HealthCheckView(APIView):
    """Simple health check for Docker healthcheck and load balancers."""
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        # Check DB connectivity
        try:
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        except Exception:
            return Response({'status': 'unhealthy', 'db': 'down'}, status=503)

        # Check Redis connectivity
        try:
            from django.core.cache import cache
            cache.set('health_check', 'ok', 10)
        except Exception:
            return Response({'status': 'unhealthy', 'redis': 'down'}, status=503)

        return Response({'status': 'healthy'})
```
