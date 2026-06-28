# Testing Strategy

## Test Categories

| Category | Framework | Location | Coverage |
|----------|-----------|----------|----------|
| Unit tests | pytest | `rates/tests/test_*.py` | Data cleaning, validation, models |
| Integration tests | pytest + DRF test client | `rates/tests/test_api_*.py` | API endpoints, auth |
| Ingestion tests | pytest + mock | `rates/tests/test_ingestion.py` | Parquet reading, error handling |

## Required Test: Mock HTTP and Assert Parsed Output

The spec explicitly requires: *"Write at least one pytest test that mocks the HTTP call and asserts the parsed output matches a known fixture."*

```python
# rates/tests/test_ingestion.py
import pytest
from unittest.mock import patch, MagicMock
from decimal import Decimal
from rates.services.ingestion import parse_rate_response
from rates.services.data_cleaner import clean_rate_record

class TestIngestionWorker:

    def test_parse_rate_from_mocked_response(self):
        """Mock HTTP response and verify parsed output matches fixture."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "provider": "Chase",
            "rate_type": "30yr_fixed_mortgage",
            "rate_value": 6.75,
            "effective_date": "2026-03-25",
            "currency": "USD",
            "source_url": "https://www.chase.com/rates/30yr_fixed_mortgage"
        }
        mock_response.text = '{"provider":"Chase",...}'

        expected = {
            "provider": "Chase",
            "rate_type": "30yr_fixed_mortgage",
            "rate_value": Decimal("6.7500"),
            "effective_date": "2026-03-25",
            "currency": "USD",
        }

        with patch('requests.get', return_value=mock_response):
            result = parse_rate_response(mock_response)

        assert result["provider"] == expected["provider"]
        assert result["rate_type"] == expected["rate_type"]
        assert result["rate_value"] == expected["rate_value"]
        assert result["effective_date"] == expected["effective_date"]
        assert result["currency"] == expected["currency"]

    def test_http_error_handled_gracefully(self):
        """Ensure HTTP errors don't crash the worker."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = Exception("Server Error")

        with patch('requests.get', return_value=mock_response):
            # Should log error and return None, not raise
            result = parse_rate_response(mock_response)
            assert result is None

    def test_timeout_handled_gracefully(self):
        """Ensure timeouts don't crash the worker."""
        import requests
        with patch('requests.get', side_effect=requests.Timeout("Connection timed out")):
            # Should be caught and logged
            result = parse_rate_response(None)
            assert result is None
```

## Data Cleaning Tests

```python
# rates/tests/test_data_cleaner.py
import pytest
from decimal import Decimal
from rates.services.data_cleaner import (
    normalize_provider,
    normalize_currency,
    validate_rate_value,
    clean_rate_record,
)

class TestProviderNormalization:
    @pytest.mark.parametrize("input_name,expected", [
        ("HSBC", "HSBC"),
        ("Hsbc", "HSBC"),
        ("hsbc", "HSBC"),
        ("Chase", "Chase"),
        ("Bank of America", "Bank of America"),
    ])
    def test_normalize_provider(self, input_name, expected):
        assert normalize_provider(input_name) == expected

class TestCurrencyNormalization:
    @pytest.mark.parametrize("input_currency,expected", [
        ("USD", "USD"),
        ("usd", "USD"),
        ("US Dollar", "USD"),
    ])
    def test_normalize_currency(self, input_currency, expected):
        assert normalize_currency(input_currency) == expected

class TestRateValueValidation:
    def test_valid_rate(self):
        is_valid, error = validate_rate_value(6.75, "30yr_fixed_mortgage")
        assert is_valid is True
        assert error == ""

    def test_null_rate(self):
        is_valid, error = validate_rate_value(None, "30yr_fixed_mortgage")
        assert is_valid is False
        assert "null" in error.lower()

    def test_negative_rate(self):
        is_valid, error = validate_rate_value(-1.5, "30yr_fixed_mortgage")
        assert is_valid is False
        assert "negative" in error.lower()

    def test_extreme_rate(self):
        is_valid, error = validate_rate_value(97.39, "30yr_fixed_mortgage")
        assert is_valid is False
        assert "20%" in error or "threshold" in error.lower()

    def test_boundary_rate_zero(self):
        is_valid, _ = validate_rate_value(0.0, "savings_easy_access")
        assert is_valid is True

    def test_boundary_rate_twenty(self):
        is_valid, _ = validate_rate_value(20.0, "30yr_fixed_mortgage")
        assert is_valid is True

class TestCleanRateRecord:
    def test_full_cleaning_pipeline(self):
        raw = {
            "provider": "hsbc",
            "rate_type": "savings_1yr_fixed",
            "rate_value": 4.7647,
            "effective_date": "2025-01-12",
            "currency": "US Dollar",
            "source_url": "https://www.hsbc.com/rates/savings_1yr_fixed",
            "raw_response_id": "abc123",
            "ingestion_ts": "2025-01-12T22:34:05",
        }

        result = clean_rate_record(raw)

        assert result["provider"] == "HSBC"
        assert result["currency"] == "USD"
        assert result["rate_value"] == Decimal("4.7647")
        assert result["is_valid"] is True
```

## API Endpoint Tests

```python
# rates/tests/test_api_latest.py
import pytest
from django.test import TestCase
from rest_framework.test import APIClient
from rates.models import Rate, Provider

@pytest.mark.django_db
class TestLatestRatesAPI:
    def setup_method(self):
        self.client = APIClient()
        # Create test data
        self.provider = Provider.objects.create(name='Chase', normalized_name='Chase')
        Rate.objects.create(
            provider=self.provider,
            rate_type='30yr_fixed_mortgage',
            rate_value='6.75',
            effective_date='2026-03-25',
            currency='USD',
            ingestion_ts='2026-03-25T18:30:00Z',
        )

    def test_get_latest_rates(self):
        response = self.client.get('/api/v1/rates/latest/')
        assert response.status_code == 200
        assert len(response.json()['data']) >= 1

    def test_filter_by_type(self):
        response = self.client.get('/api/v1/rates/latest/?type=30yr_fixed_mortgage')
        assert response.status_code == 200
        for rate in response.json()['data']:
            assert rate['rate_type'] == '30yr_fixed_mortgage'

    def test_invalid_type_returns_empty(self):
        response = self.client.get('/api/v1/rates/latest/?type=nonexistent')
        assert response.status_code == 200
        assert len(response.json()['data']) == 0
```

```python
# rates/tests/test_api_history.py
@pytest.mark.django_db
class TestRateHistoryAPI:
    def test_requires_provider_and_type(self):
        response = self.client.get('/api/v1/rates/history/')
        assert response.status_code == 400
        assert 'errors' in response.json()

    def test_paginated_response(self):
        # Create 60 rate records
        # ...
        response = self.client.get(
            '/api/v1/rates/history/?provider=Chase&type=30yr_fixed_mortgage&page_size=50'
        )
        assert response.status_code == 200
        assert len(response.json()['data']) <= 50
        assert 'meta' in response.json()
        assert response.json()['meta']['total_pages'] >= 1

    def test_date_filtering(self):
        response = self.client.get(
            '/api/v1/rates/history/?provider=Chase&type=30yr_fixed_mortgage'
            '&from=2026-03-01&to=2026-03-31'
        )
        assert response.status_code == 200
```

```python
# rates/tests/test_api_ingest.py
@pytest.mark.django_db
class TestIngestAPI:
    def setup_method(self):
        self.client = APIClient()
        self.valid_payload = {
            "provider": "Chase",
            "rate_type": "30yr_fixed_mortgage",
            "rate_value": 6.75,
            "effective_date": "2026-03-26",
            "source_url": "https://www.chase.com/rates",
            "currency": "USD",
        }

    def test_unauthenticated_returns_401(self):
        response = self.client.post('/api/v1/rates/ingest/', self.valid_payload, format='json')
        assert response.status_code == 401

    def test_invalid_token_returns_401(self):
        self.client.credentials(HTTP_AUTHORIZATION='Bearer wrongtoken')
        response = self.client.post('/api/v1/rates/ingest/', self.valid_payload, format='json')
        assert response.status_code == 401

    def test_valid_ingest(self):
        self.client.credentials(HTTP_AUTHORIZATION='Bearer test-token')
        response = self.client.post('/api/v1/rates/ingest/', self.valid_payload, format='json')
        assert response.status_code == 201
        assert response.json()['data']['provider'] == 'Chase'

    def test_validation_errors_return_400(self):
        self.client.credentials(HTTP_AUTHORIZATION='Bearer test-token')
        bad_payload = {**self.valid_payload, 'rate_value': -5.0}
        response = self.client.post('/api/v1/rates/ingest/', bad_payload, format='json')
        assert response.status_code == 400
        assert 'errors' in response.json()

    def test_invalid_rate_type_returns_400(self):
        self.client.credentials(HTTP_AUTHORIZATION='Bearer test-token')
        bad_payload = {**self.valid_payload, 'rate_type': 'invalid_type'}
        response = self.client.post('/api/v1/rates/ingest/', bad_payload, format='json')
        assert response.status_code == 400

    def test_cache_invalidated_after_ingest(self):
        """After a successful ingest, the latest rates cache should be invalidated."""
        from django.core.cache import cache
        cache.set('rates:latest', 'old_data', 300)

        self.client.credentials(HTTP_AUTHORIZATION='Bearer test-token')
        self.client.post('/api/v1/rates/ingest/', self.valid_payload, format='json')

        assert cache.get('rates:latest') is None
```

## Pytest Configuration

```ini
# pytest.ini
[pytest]
DJANGO_SETTINGS_MODULE = config.settings
python_files = tests.py test_*.py *_tests.py
addopts = -v --tb=short --strict-markers
markers =
    slow: marks tests as slow (deselect with '-m "not slow"')
```

## Test Fixtures

```python
# rates/tests/conftest.py
import pytest
from rates.models import Provider, Rate, RawResponse
from django.utils import timezone
from datetime import date, timedelta

@pytest.fixture
def provider_chase(db):
    return Provider.objects.create(name='Chase', normalized_name='Chase')

@pytest.fixture
def provider_hsbc(db):
    return Provider.objects.create(name='HSBC', normalized_name='HSBC')

@pytest.fixture
def sample_rates(provider_chase, provider_hsbc):
    """Create a set of sample rates for testing."""
    rates = []
    base_date = date(2026, 3, 1)
    for i in range(30):
        d = base_date + timedelta(days=i)
        rates.append(Rate(
            provider=provider_chase,
            rate_type='30yr_fixed_mortgage',
            rate_value=f'{6.5 + i * 0.01:.4f}',
            effective_date=d,
            currency='USD',
            ingestion_ts=timezone.make_aware(
                timezone.datetime(d.year, d.month, d.day, 12, 0, 0)
            ),
        ))
    Rate.objects.bulk_create(rates)
    return rates

@pytest.fixture
def api_client():
    from rest_framework.test import APIClient
    return APIClient()

@pytest.fixture
def authenticated_client(api_client):
    api_client.credentials(HTTP_AUTHORIZATION='Bearer test-token')
    return api_client
```

## Coverage Target

| Module | Target | Rationale |
|--------|--------|-----------|
| `services/data_cleaner.py` | 95%+ | Core business logic, fully unit-testable |
| `services/ingestion.py` | 80%+ | Complex logic, mock-heavy |
| `views.py` | 80%+ | API contract validation |
| `authentication.py` | 90%+ | Security-critical |
| Overall | 75%+ | Pragmatic for 48-hour window |
