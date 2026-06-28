"""
Tests for data cleaning service.

Covers all 7 data quality issues identified in rates_seed.parquet.
"""
import pytest
from decimal import Decimal

from rates.services.data_cleaner import (
    normalize_provider,
    normalize_currency,
    validate_rate_value,
    validate_dates,
    validate_rate_type,
    clean_rate_record,
    VALID_RATE_TYPES,
)


class TestProviderNormalization:
    """Provider casing fix: HSBC / Hsbc / hsbc → HSBC"""

    @pytest.mark.parametrize('input_name,expected', [
        ('HSBC', 'HSBC'),
        ('Hsbc', 'HSBC'),
        ('hsbc', 'HSBC'),
        ('Chase', 'Chase'),
        ('chase', 'Chase'),
        ('Bank of America', 'Bank of America'),
        ('Wells Fargo', 'Wells Fargo'),
        ('PNC Bank', 'PNC Bank'),
        ('TD Bank', 'TD Bank'),
        ('Truist', 'Truist'),
        ('US Bancorp', 'US Bancorp'),
        ('Capital One', 'Capital One'),
        ('Citibank', 'Citibank'),
    ])
    def test_normalize_provider(self, input_name, expected):
        assert normalize_provider(input_name) == expected

    def test_unknown_provider_preserved(self):
        """Unknown providers should not be silently dropped."""
        result = normalize_provider('New Bank XYZ')
        assert result == 'New Bank XYZ'

    def test_empty_string(self):
        result = normalize_provider('')
        assert result == ''


class TestCurrencyNormalization:
    """Currency variant fix: USD / usd / US Dollar → USD"""

    @pytest.mark.parametrize('input_currency,expected', [
        ('USD', 'USD'),
        ('usd', 'USD'),
        ('US Dollar', 'USD'),
        ('Us Dollar', 'USD'),
        ('us dollar', 'USD'),
    ])
    def test_normalize_currency(self, input_currency, expected):
        assert normalize_currency(input_currency) == expected

    def test_unknown_currency_uppercased(self):
        assert normalize_currency('eur') == 'EUR'


class TestRateValueValidation:
    """Rate value validation: null, negative, >20% thresholds."""

    def test_valid_rate(self):
        is_valid, error = validate_rate_value(6.75, '30yr_fixed_mortgage')
        assert is_valid is True
        assert error == ''

    def test_null_rate(self):
        is_valid, error = validate_rate_value(None, '30yr_fixed_mortgage')
        assert is_valid is False
        assert 'null' in error.lower()

    def test_negative_rate(self):
        is_valid, error = validate_rate_value(-1.5, '30yr_fixed_mortgage')
        assert is_valid is False
        assert 'negative' in error.lower() or 'min' in error.lower()

    def test_extreme_high_rate(self):
        is_valid, error = validate_rate_value(97.39, '30yr_fixed_mortgage')
        assert is_valid is False
        assert '20%' in error or 'threshold' in error.lower() or 'exceeds' in error.lower()

    def test_boundary_zero_is_valid(self):
        is_valid, _ = validate_rate_value(0.0, 'savings_easy_access')
        assert is_valid is True

    def test_boundary_twenty_is_valid(self):
        is_valid, _ = validate_rate_value(20.0, '30yr_fixed_mortgage')
        assert is_valid is True

    def test_just_above_twenty_is_invalid(self):
        is_valid, _ = validate_rate_value(20.01, '30yr_fixed_mortgage')
        assert is_valid is False

    def test_just_below_zero_is_invalid(self):
        is_valid, _ = validate_rate_value(-0.001, 'savings_1yr_fixed')
        assert is_valid is False

    @pytest.mark.parametrize('value', [-1.8440, -1.7301, -1.7121, -1.6253])
    def test_all_known_negative_rates_rejected(self, value):
        is_valid, _ = validate_rate_value(value, '5yr_arm_mortgage')
        assert is_valid is False

    @pytest.mark.parametrize('value', [97.3949, 95.9641, 91.4585, 72.9289])
    def test_all_known_extreme_rates_rejected(self, value):
        is_valid, _ = validate_rate_value(value, '30yr_fixed_mortgage')
        assert is_valid is False


class TestDateValidation:
    """Date mismatch detection: effective_date >> ingestion_ts"""
    from datetime import date, datetime, timezone

    def test_matching_dates_valid(self):
        from datetime import date, datetime, timezone
        eff = date(2026, 3, 25)
        ing = datetime(2026, 3, 25, 12, 0, 0, tzinfo=timezone.utc)
        is_valid, _ = validate_dates(eff, ing)
        assert is_valid is True

    def test_null_effective_date_invalid(self):
        is_valid, err = validate_dates(None, None)
        assert is_valid is False
        assert 'null' in err.lower()

    def test_far_future_effective_date_still_valid(self):
        """50 mismatched rows should be ingested (just warned)."""
        from datetime import date, datetime, timezone
        eff = date(2026, 9, 13)  # future
        ing = datetime(2025, 1, 5, tzinfo=timezone.utc)  # past
        is_valid, _ = validate_dates(eff, ing)
        # Should be valid (just warns) — these rows should be ingested
        assert is_valid is True


class TestRateTypeValidation:
    def test_valid_rate_types(self):
        for rt in VALID_RATE_TYPES:
            is_valid, _ = validate_rate_type(rt)
            assert is_valid is True

    def test_invalid_rate_type(self):
        is_valid, error = validate_rate_type('40yr_fixed_mortgage')
        assert is_valid is False
        assert 'unknown' in error.lower() or 'invalid' in error.lower()


class TestCleanRateRecord:
    """Integration test: clean_rate_record orchestrates all above."""

    def test_full_cleaning_pipeline(self):
        raw = {
            'provider': 'hsbc',
            'rate_type': 'savings_1yr_fixed',
            'rate_value': 4.7647,
            'effective_date': '2025-01-12',
            'currency': 'US Dollar',
            'source_url': 'https://www.hsbc.com/rates/savings_1yr_fixed',
            'raw_response_id': 'abc-123',
            'ingestion_ts': '2025-01-12T22:34:05',
        }

        result = clean_rate_record(raw)

        assert result['normalized_provider'] == 'HSBC'
        assert result['normalized_currency'] == 'USD'
        assert result['rate_value'] == Decimal('4.7647')
        assert result['is_valid'] is True
        assert result['validation_errors'] == []

    def test_null_rate_value_marked_invalid(self):
        raw = {
            'provider': 'Chase',
            'rate_type': '30yr_fixed_mortgage',
            'rate_value': None,
            'effective_date': '2025-01-12',
            'currency': 'USD',
            'source_url': '',
            'raw_response_id': 'abc-456',
            'ingestion_ts': '2025-01-12T22:34:05',
        }

        result = clean_rate_record(raw)
        assert result['is_valid'] is False
        assert len(result['validation_errors']) > 0

    def test_negative_rate_marked_invalid(self):
        raw = {
            'provider': 'Citibank',
            'rate_type': '5yr_arm_mortgage',
            'rate_value': -1.844,
            'effective_date': '2025-01-12',
            'currency': 'USD',
            'source_url': '',
            'raw_response_id': 'abc-789',
            'ingestion_ts': '2025-01-12T22:34:05',
        }

        result = clean_rate_record(raw)
        assert result['is_valid'] is False

    def test_extreme_rate_marked_invalid(self):
        raw = {
            'provider': 'Truist',
            'rate_type': '5yr_arm_mortgage',
            'rate_value': 97.3949,
            'effective_date': '2025-01-12',
            'currency': 'USD',
            'source_url': '',
            'raw_response_id': 'abc-999',
            'ingestion_ts': '2025-01-12T22:34:05',
        }

        result = clean_rate_record(raw)
        assert result['is_valid'] is False
