#!/bin/bash
set -e

# Update settings to use SQLite and LocMemCache for running without Docker
sed -i '' "s/get_env('POSTGRES_DB', 'rate_tracker')/get_env('POSTGRES_DB', '')/g" config/settings.py
sed -i '' "s/'ENGINE': 'django.db.backends.postgresql'/'ENGINE': 'django.db.backends.sqlite3' if not get_env('POSTGRES_DB') else 'django.db.backends.postgresql'/g" config/settings.py
sed -i '' "s/'NAME': get_env('POSTGRES_DB', '')/'NAME': get_env('POSTGRES_DB') if get_env('POSTGRES_DB') else BASE_DIR \/ 'db.sqlite3'/g" config/settings.py

sed -i '' "s/get_env('REDIS_URL', 'redis:\/\/localhost:6379\/0')/get_env('REDIS_URL', '')/g" config/settings.py
sed -i '' "s/'BACKEND': 'django_redis.cache.RedisCache'/'BACKEND': 'django.core.cache.backends.locmem.LocMemCache' if not get_env('REDIS_URL') else 'django_redis.cache.RedisCache'/g" config/settings.py

# Export empty vars so it falls back to SQLite and LocMem
export POSTGRES_DB=
export REDIS_URL=

echo "Running migrations..."
source venv/bin/activate
python manage.py migrate

echo "Seeding database..."
python manage.py seed_data --batch-size 5000

echo "Starting Django server in background..."
python manage.py runserver 8000 &
DJANGO_PID=$!

echo "Starting Next.js frontend in background..."
cd frontend
npm run dev &
NEXT_PID=$!

echo "Both servers are starting..."
wait $DJANGO_PID $NEXT_PID
