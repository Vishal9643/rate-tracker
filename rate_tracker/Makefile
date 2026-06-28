.PHONY: up down seed test logs migrate shell reset build

## Start all services (detached)
up:
	docker-compose up -d --build

## Stop all services
down:
	docker-compose down

## Seed the database from parquet file
seed:
	docker-compose exec django python manage.py seed_data

## Run all tests
test:
	docker-compose exec django pytest -v --tb=short

## Tail all logs
logs:
	docker-compose logs -f

## Run Django migrations
migrate:
	docker-compose exec django python manage.py migrate

## Django shell
shell:
	docker-compose exec django python manage.py shell

## Full reset: stop, remove volumes, rebuild, migrate, seed
reset:
	docker-compose down -v
	docker-compose up -d --build
	@echo "Waiting for services to be healthy..."
	@sleep 30
	docker-compose exec django python manage.py migrate --noinput
	docker-compose exec django python manage.py seed_data

## Build images without starting
build:
	docker-compose build

## Show service status
status:
	docker-compose ps
