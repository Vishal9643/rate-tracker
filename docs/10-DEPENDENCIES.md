# Python Dependencies Reference

## requirements.txt

```
# Core
Django>=5.0,<6.0
djangorestframework>=3.15,<4.0

# Database
psycopg2-binary>=2.9

# Cache
redis>=5.0
django-redis>=5.4

# Task Queue
celery>=5.4
django-celery-beat>=2.6

# Data Processing
pyarrow>=15.0
pandas>=2.2

# Testing
pytest>=8.0
pytest-django>=4.8
pytest-cov>=5.0

# Observability
python-json-logger>=2.0

# Server
gunicorn>=22.0
```

## Frontend package.json dependencies

```json
{
  "dependencies": {
    "next": "^14.0.0",
    "react": "^18.0.0",
    "react-dom": "^18.0.0",
    "swr": "^2.2.0",
    "recharts": "^2.10.0"
  },
  "devDependencies": {
    "@types/node": "^20.0.0",
    "@types/react": "^18.0.0",
    "typescript": "^5.0.0",
    "eslint": "^8.0.0",
    "eslint-config-next": "^14.0.0"
  }
}
```
