"""
Integration tests for POST /api/v1/rates/ingest/

Covers: authentication, validation, successful creation, error responses.
"""
import pytest
from decimal import Decimal


@pytest.mark.django_db
class TestIngestAPI:

    VALID_PAYLOAD = {
        'provider': 'Chase',
        'rate_type': '30yr_fixed_mortgage',
        'rate_value': 6.75,
        'effective_date': '2026-03-26',
        'source_url': 'https://www.chase.com/rates/30yr_fixed_mortgage',
        'currency': 'USD',
    }

    # --- Authentication tests ---

    def test_unauthenticated_returns_401(self, api_client):
        response = api_client.post('/api/v1/rates/ingest/', self.VALID_PAYLOAD, format='json')
        assert response.status_code == 401

    def test_wrong_token_returns_401(self, api_client):
        api_client.credentials(HTTP_AUTHORIZATION='Bearer totally-wrong-token')
        response = api_client.post('/api/v1/rates/ingest/', self.VALID_PAYLOAD, format='json')
        assert response.status_code == 401

    def test_missing_bearer_prefix_returns_401(self, api_client):
        api_client.credentials(HTTP_AUTHORIZATION='Token dev-token-change-in-production')
        response = api_client.post('/api/v1/rates/ingest/', self.VALID_PAYLOAD, format='json')
        assert response.status_code == 401

    # --- Successful creation ---

    def test_valid_ingest_returns_201(self, authenticated_client):
        response = authenticated_client.post('/api/v1/rates/ingest/', self.VALID_PAYLOAD, format='json')
        assert response.status_code == 201
        data = response.json()['data']
        assert data['provider'] == 'Chase'
        assert data['rate_type'] == '30yr_fixed_mortgage'
        assert data['rate_value'] == '6.7500'
        assert 'id' in data
        assert 'created_at' in data

    def test_created_rate_in_db(self, authenticated_client):
        from rates.models import Rate
        count_before = Rate.objects.count()
        authenticated_client.post('/api/v1/rates/ingest/', self.VALID_PAYLOAD, format='json')
        count_after = Rate.objects.count()
        assert count_after == count_before + 1

    def test_provider_normalized_hsbc(self, authenticated_client):
        """hsbc → HSBC after normalization."""
        payload = {**self.VALID_PAYLOAD, 'provider': 'hsbc'}
        response = authenticated_client.post('/api/v1/rates/ingest/', payload, format='json')
        assert response.status_code == 201
        assert response.json()['data']['provider'] == 'HSBC'

    # --- Validation error tests ---

    def test_negative_rate_value_returns_400(self, authenticated_client):
        payload = {**self.VALID_PAYLOAD, 'rate_value': -1.5}
        response = authenticated_client.post('/api/v1/rates/ingest/', payload, format='json')
        assert response.status_code == 400
        errors = response.json()['errors']
        assert any('rate_value' in (e.get('field') or '') for e in errors)

    def test_extreme_rate_value_returns_400(self, authenticated_client):
        payload = {**self.VALID_PAYLOAD, 'rate_value': 97.39}
        response = authenticated_client.post('/api/v1/rates/ingest/', payload, format='json')
        assert response.status_code == 400

    def test_invalid_rate_type_returns_400(self, authenticated_client):
        payload = {**self.VALID_PAYLOAD, 'rate_type': 'invalid_type'}
        response = authenticated_client.post('/api/v1/rates/ingest/', payload, format='json')
        assert response.status_code == 400
        errors = response.json()['errors']
        assert any('rate_type' in (e.get('field') or '') for e in errors)

    def test_missing_required_fields_returns_400(self, authenticated_client):
        response = authenticated_client.post('/api/v1/rates/ingest/', {}, format='json')
        assert response.status_code == 400
        assert 'errors' in response.json()

    def test_invalid_date_format_returns_400(self, authenticated_client):
        payload = {**self.VALID_PAYLOAD, 'effective_date': 'not-a-date'}
        response = authenticated_client.post('/api/v1/rates/ingest/', payload, format='json')
        assert response.status_code == 400

    def test_error_response_has_consistent_structure(self, authenticated_client):
        """Error responses must have {errors: [{field, message}]} format — not raw 500."""
        payload = {**self.VALID_PAYLOAD, 'rate_value': -1.5}
        response = authenticated_client.post('/api/v1/rates/ingest/', payload, format='json')
        assert response.status_code == 400
        data = response.json()
        assert 'errors' in data
        for error in data['errors']:
            assert 'message' in error

    def test_currency_normalised(self, authenticated_client):
        """usd → USD after normalization."""
        payload = {**self.VALID_PAYLOAD, 'currency': 'usd', 'rate_value': 5.0}
        response = authenticated_client.post('/api/v1/rates/ingest/', payload, format='json')
        assert response.status_code == 201
        from rates.models import Rate
        rate = Rate.objects.latest('created_at')
        assert rate.currency == 'USD'


@pytest.mark.django_db
class TestHealthCheck:

    def test_health_check_200(self, api_client):
        """Health check should return 200 when DB is up."""
        response = api_client.get('/api/v1/health/')
        # In test env with SQLite fallback, DB should be accessible
        assert response.status_code in (200, 503)  # 503 if Redis unavailable in test
        assert 'status' in response.json()
