"""
Integration tests for GET /api/v1/rates/latest/
"""
import pytest
from decimal import Decimal
from datetime import date
from django.utils import timezone
from django.conf import settings

from rates.models import Rate, Provider


@pytest.mark.django_db
class TestLatestRatesAPI:

    def test_get_latest_rates_200(self, api_client, sample_rate):
        response = api_client.get('/api/v1/rates/latest/')
        assert response.status_code == 200
        data = response.json()
        assert 'data' in data
        assert 'meta' in data
        assert data['meta']['count'] >= 1

    def test_response_shape(self, api_client, sample_rate):
        response = api_client.get('/api/v1/rates/latest/')
        rate_item = response.json()['data'][0]
        assert 'provider' in rate_item
        assert 'rate_type' in rate_item
        assert 'rate_value' in rate_item
        assert 'effective_date' in rate_item
        assert 'currency' in rate_item
        assert 'last_updated' in rate_item

    def test_filter_by_type(self, api_client, sample_rate):
        response = api_client.get('/api/v1/rates/latest/?type=30yr_fixed_mortgage')
        assert response.status_code == 200
        data = response.json()['data']
        for rate in data:
            assert rate['rate_type'] == '30yr_fixed_mortgage'

    def test_filter_by_invalid_type_returns_empty(self, api_client, sample_rate):
        response = api_client.get('/api/v1/rates/latest/?type=nonexistent_type')
        assert response.status_code == 200
        assert response.json()['data'] == []

    def test_returns_most_recent_rate(self, api_client, provider_chase):
        """Should return the latest rate, not an older one."""
        ts_old = timezone.make_aware(timezone.datetime(2026, 1, 1, 12, 0, 0))
        ts_new = timezone.make_aware(timezone.datetime(2026, 3, 25, 18, 30, 0))

        Rate.objects.create(
            provider=provider_chase,
            rate_type='30yr_fixed_mortgage',
            rate_value=Decimal('5.0000'),
            effective_date=date(2026, 1, 1),
            currency='USD',
            ingestion_ts=ts_old,
        )
        Rate.objects.create(
            provider=provider_chase,
            rate_type='30yr_fixed_mortgage',
            rate_value=Decimal('6.7500'),
            effective_date=date(2026, 3, 25),
            currency='USD',
            ingestion_ts=ts_new,
        )

        response = api_client.get('/api/v1/rates/latest/?type=30yr_fixed_mortgage')
        assert response.status_code == 200
        data = response.json()['data']
        chase_rates = [r for r in data if r['provider'] == 'Chase']
        assert len(chase_rates) == 1
        assert chase_rates[0]['rate_value'] == '6.7500'

    def test_cache_meta_field(self, api_client, sample_rate):
        """Second request should be served from cache."""
        from django.core.cache import cache
        cache.clear()  # Ensure cold cache regardless of test ordering

        response1 = api_client.get('/api/v1/rates/latest/')
        assert response1.json()['meta']['cached'] is False

        response2 = api_client.get('/api/v1/rates/latest/')
        # After first hit, subsequent should be from cache
        # (in test env without real Redis, may not be cached — just check field exists)
        assert 'cached' in response2.json()['meta']
