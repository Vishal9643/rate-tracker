"""
Shared pytest fixtures for Rate-Tracker tests.
"""
import pytest
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from rates.models import Provider, Rate, RawResponse, IngestionJob


@pytest.fixture
def provider_chase(db):
    return Provider.objects.create(name='Chase', normalized_name='Chase')


@pytest.fixture
def provider_wells_fargo(db):
    return Provider.objects.create(name='Wells Fargo', normalized_name='Wells Fargo')


@pytest.fixture
def provider_hsbc(db):
    return Provider.objects.create(name='HSBC', normalized_name='HSBC')


@pytest.fixture
def ingestion_job(db):
    return IngestionJob.objects.create(
        status='completed',
        source_file='rates_seed.parquet',
        total_rows=100,
        processed_rows=98,
        failed_rows=2,
    )


@pytest.fixture
def raw_response(db, ingestion_job):
    return RawResponse.objects.create(
        raw_response_id='test-raw-001',
        raw_data={'provider': 'Chase', 'rate_type': '30yr_fixed_mortgage'},
        source_url='https://www.chase.com/rates/30yr_fixed_mortgage',
        ingestion_job=ingestion_job,
        status='processed',
    )


@pytest.fixture
def sample_rate(db, provider_chase, raw_response):
    return Rate.objects.create(
        provider=provider_chase,
        rate_type='30yr_fixed_mortgage',
        rate_value=Decimal('6.7500'),
        effective_date=date(2026, 3, 25),
        currency='USD',
        source_url='https://www.chase.com/rates/30yr_fixed_mortgage',
        ingestion_ts=timezone.make_aware(
            timezone.datetime(2026, 3, 25, 18, 30, 0)
        ),
        raw_response=raw_response,
    )


@pytest.fixture
def sample_rates_30d(db, provider_chase, provider_wells_fargo):
    """30 days of rate data for chart tests."""
    rates = []
    base_date = date(2026, 2, 25)
    for i in range(30):
        d = base_date + timedelta(days=i)
        ts = timezone.make_aware(timezone.datetime(d.year, d.month, d.day, 12, 0, 0))
        rates.append(Rate(
            provider=provider_chase,
            rate_type='30yr_fixed_mortgage',
            rate_value=Decimal(f'{6.5 + i * 0.01:.4f}'),
            effective_date=d,
            currency='USD',
            ingestion_ts=ts,
        ))
        rates.append(Rate(
            provider=provider_wells_fargo,
            rate_type='30yr_fixed_mortgage',
            rate_value=Decimal(f'{6.6 + i * 0.01:.4f}'),
            effective_date=d,
            currency='USD',
            ingestion_ts=ts,
        ))
    Rate.objects.bulk_create(rates)
    return rates


@pytest.fixture
def api_client():
    from rest_framework.test import APIClient
    return APIClient()


@pytest.fixture
def authenticated_client(api_client):
    """API client with valid bearer token from settings."""
    from django.conf import settings
    api_client.credentials(HTTP_AUTHORIZATION=f'Bearer {settings.API_INGEST_TOKEN}')
    return api_client
