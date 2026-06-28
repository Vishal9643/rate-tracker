"""
Integration tests for GET /api/v1/rates/history/
"""
import pytest
from decimal import Decimal
from datetime import date, timedelta
from django.utils import timezone

from rates.models import Rate


@pytest.mark.django_db
class TestRateHistoryAPI:

    def test_missing_provider_returns_400(self, api_client):
        response = api_client.get('/api/v1/rates/history/?type=30yr_fixed_mortgage')
        assert response.status_code == 400
        data = response.json()
        assert 'errors' in data
        assert any(e['field'] == 'provider' for e in data['errors'])

    def test_missing_type_returns_400(self, api_client):
        response = api_client.get('/api/v1/rates/history/?provider=Chase')
        assert response.status_code == 400
        data = response.json()
        assert 'errors' in data
        assert any(e['field'] == 'type' for e in data['errors'])

    def test_both_required_params_returns_200(self, api_client, sample_rates_30d):
        response = api_client.get(
            '/api/v1/rates/history/?provider=Chase&type=30yr_fixed_mortgage'
        )
        assert response.status_code == 200
        data = response.json()
        assert 'data' in data
        assert 'meta' in data

    def test_pagination_structure(self, api_client, sample_rates_30d):
        response = api_client.get(
            '/api/v1/rates/history/?provider=Chase&type=30yr_fixed_mortgage&page_size=10'
        )
        assert response.status_code == 200
        meta = response.json()['meta']
        assert 'count' in meta
        assert 'page' in meta
        assert 'page_size' in meta
        assert 'total_pages' in meta

    def test_page_size_enforced(self, api_client, sample_rates_30d):
        response = api_client.get(
            '/api/v1/rates/history/?provider=Chase&type=30yr_fixed_mortgage&page_size=10'
        )
        assert response.status_code == 200
        assert len(response.json()['data']) <= 10

    def test_max_page_size_100(self, api_client, sample_rates_30d):
        """page_size > 100 should be capped at 100."""
        response = api_client.get(
            '/api/v1/rates/history/?provider=Chase&type=30yr_fixed_mortgage&page_size=999'
        )
        assert response.status_code == 200
        assert len(response.json()['data']) <= 100

    def test_date_filter_from_to(self, api_client, sample_rates_30d):
        response = api_client.get(
            '/api/v1/rates/history/?provider=Chase&type=30yr_fixed_mortgage'
            '&from=2026-03-01&to=2026-03-10'
        )
        assert response.status_code == 200
        data = response.json()['data']
        for item in data:
            assert '2026-03-01' <= item['effective_date'] <= '2026-03-10'

    def test_from_after_to_returns_400(self, api_client):
        response = api_client.get(
            '/api/v1/rates/history/?provider=Chase&type=30yr_fixed_mortgage'
            '&from=2026-03-31&to=2026-03-01'
        )
        assert response.status_code == 400
        errors = response.json()['errors']
        assert any('from' in (e.get('field') or '') for e in errors)

    def test_invalid_date_format_returns_400(self, api_client):
        response = api_client.get(
            '/api/v1/rates/history/?provider=Chase&type=30yr_fixed_mortgage'
            '&from=not-a-date'
        )
        assert response.status_code == 400

    def test_meta_includes_context(self, api_client, sample_rates_30d):
        response = api_client.get(
            '/api/v1/rates/history/?provider=Chase&type=30yr_fixed_mortgage'
        )
        meta = response.json()['meta']
        assert meta['provider'] == 'Chase'
        assert meta['rate_type'] == '30yr_fixed_mortgage'
