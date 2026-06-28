"""
Data cleaning and normalisation for Rate-Tracker ingestion pipeline.

Handles the 7 known data quality issues in rates_seed.parquet:
1. Provider casing inconsistency (HSBC / Hsbc / hsbc)
2. Currency inconsistency (USD / usd / US Dollar)
3. Null rate_value (200 rows)
4. Negative rates (15 rows)
5. Extreme rates > 20% (15 rows)
6. Date mismatches (50 rows) — ingested with warning
7. Future effective dates (50 rows) — ingested with warning
"""
import logging
import math
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

import pandas as pd

logger = logging.getLogger('rates.cleaner')

# ---------------------------------------------------------------------------
# Normalisation lookup tables
# ---------------------------------------------------------------------------

# All known provider name variants → canonical form
# Case-sensitive keys to preserve original casing awareness.
PROVIDER_NORMALIZATION: dict[str, str] = {
    'HSBC': 'HSBC',
    'Hsbc': 'HSBC',
    'hsbc': 'HSBC',
    'Bank of America': 'Bank of America',
    'bank of america': 'Bank of America',
    'Chase': 'Chase',
    'chase': 'Chase',
    'Citibank': 'Citibank',
    'citibank': 'Citibank',
    'PNC Bank': 'PNC Bank',
    'pnc bank': 'PNC Bank',
    'TD Bank': 'TD Bank',
    'td bank': 'TD Bank',
    'Truist': 'Truist',
    'truist': 'Truist',
    'US Bancorp': 'US Bancorp',
    'us bancorp': 'US Bancorp',
    'Wells Fargo': 'Wells Fargo',
    'wells fargo': 'Wells Fargo',
    'Capital One': 'Capital One',
    'capital one': 'Capital One',
}

CURRENCY_NORMALIZATION: dict[str, str] = {
    'USD': 'USD',
    'usd': 'USD',
    'US Dollar': 'USD',
    'us dollar': 'USD',
    'Us Dollar': 'USD',
}

VALID_RATE_TYPES = frozenset([
    '15yr_fixed_mortgage',
    '30yr_fixed_mortgage',
    '5yr_arm_mortgage',
    'savings_1yr_fixed',
    'savings_easy_access',
])

# Validation thresholds for rate_value
RATE_VALUE_MIN: float = 0.0
RATE_VALUE_MAX: float = 20.0

# Max days difference between effective_date and ingestion_ts before warning
DATE_MISMATCH_WARN_DAYS: int = 90


# ---------------------------------------------------------------------------
# Normalisation functions
# ---------------------------------------------------------------------------

def normalize_provider(name: str) -> str:
    """
    Return the canonical provider name.
    Preserves unknown providers as-is (strip + title-case) so no data is silently lost.
    """
    if not name:
        return name
    name = str(name).strip()
    # Try exact match first
    canonical = PROVIDER_NORMALIZATION.get(name)
    if canonical:
        return canonical
    # Try case-insensitive fallback
    canonical = PROVIDER_NORMALIZATION.get(name.lower())
    if canonical:
        return canonical
    # Unknown provider: preserve as-is, log for ops awareness
    logger.warning(f"Unknown provider '{name}' — preserving as-is")
    return name


def normalize_currency(currency: str) -> str:
    """Normalise currency string to ISO 4217 code (USD)."""
    if not currency:
        return 'USD'
    currency = str(currency).strip()
    return CURRENCY_NORMALIZATION.get(currency, currency.upper())


# ---------------------------------------------------------------------------
# Validation functions
# ---------------------------------------------------------------------------

def validate_rate_value(value, rate_type: str = '') -> tuple[bool, str]:
    """
    Returns (is_valid, error_message).

    Rejects: nulls, negatives, values > 20%.
    Rationale: negative rates and rates > 20% are clearly data errors in this
    US mortgage/savings dataset. 20% is a generous upper bound for any
    historically realistic rate in this domain.
    """
    if value is None:
        return False, "rate_value is null"

    try:
        fval = float(value)
    except (TypeError, ValueError):
        return False, f"rate_value '{value}' is not a number"

    if math.isnan(fval):
        return False, "rate_value is NaN"

    if fval < RATE_VALUE_MIN:
        return False, f"Negative rate: {fval} (min allowed: {RATE_VALUE_MIN})"

    if fval > RATE_VALUE_MAX:
        return False, f"Rate {fval}% exceeds 20% threshold — likely corrupt data"

    return True, ""


def validate_dates(
    effective_date,
    ingestion_ts,
) -> tuple[bool, str]:
    """
    Returns (is_valid, warning_message).

    We always ingest these records (return is_valid=True) but emit a warning
    when effective_date is unreasonably far into the future relative to ingestion_ts.
    These 50 rows could be legitimate forward-dated rate announcements.
    """
    if effective_date is None:
        return False, "effective_date is null"

    # Coerce types
    if isinstance(effective_date, str):
        try:
            effective_date = date.fromisoformat(effective_date)
        except ValueError:
            return False, f"Cannot parse effective_date: '{effective_date}'"

    if isinstance(ingestion_ts, (datetime,)):
        ingestion_date = ingestion_ts.date()
    elif isinstance(ingestion_ts, str):
        try:
            ingestion_date = datetime.fromisoformat(ingestion_ts).date()
        except ValueError:
            ingestion_date = None
    else:
        ingestion_date = None

    if ingestion_date and isinstance(effective_date, date):
        delta = (effective_date - ingestion_date).days
        if delta > DATE_MISMATCH_WARN_DAYS:
            # Warning only — still ingest
            logger.warning(
                f"effective_date {effective_date} is {delta} days after "
                f"ingestion_ts {ingestion_ts} — may be a forward-dated rate"
            )

    return True, ""


def validate_rate_type(rate_type: str) -> tuple[bool, str]:
    """Validate that rate_type is one of the known types."""
    if rate_type not in VALID_RATE_TYPES:
        return False, f"Unknown rate_type '{rate_type}'"
    return True, ""


# ---------------------------------------------------------------------------
# Master cleaning function
# ---------------------------------------------------------------------------

def clean_rate_record(raw: dict) -> dict:
    """
    Orchestrates all normalisation and validation steps.

    Returns the cleaned dict with added keys:
      - is_valid (bool)
      - validation_errors (list[str])
      - normalized_provider (str)
      - normalized_currency (str)
    """
    errors: list[str] = []

    provider_raw = raw.get('provider', '')
    currency_raw = raw.get('currency', 'USD')
    rate_value = raw.get('rate_value')
    rate_type = str(raw.get('rate_type', ''))
    effective_date = raw.get('effective_date')
    ingestion_ts = raw.get('ingestion_ts')

    # Step 1: Normalise provider
    normalized_provider = normalize_provider(str(provider_raw).strip() if provider_raw else '')

    # Step 2: Normalise currency
    normalized_currency = normalize_currency(str(currency_raw).strip() if currency_raw else 'USD')

    # Step 3: Validate rate_value (skip on failure)
    # Handle pandas NA / numpy nan
    if hasattr(rate_value, '__class__') and rate_value.__class__.__name__ in ('NAType', 'float'):
        try:
            if pd.isna(rate_value):
                rate_value = None
        except (TypeError, ValueError):
            pass

    rv_valid, rv_error = validate_rate_value(rate_value, rate_type)
    if not rv_valid:
        errors.append(rv_error)

    # Step 4: Validate dates (warns but doesn't reject)
    dt_valid, dt_error = validate_dates(effective_date, ingestion_ts)
    if not dt_valid:
        errors.append(dt_error)

    # Step 5: Rate type validation
    if rate_type:
        rt_valid, rt_error = validate_rate_type(rate_type)
        if not rt_valid:
            errors.append(rt_error)

    is_valid = len(errors) == 0

    cleaned = {
        **raw,
        'provider': provider_raw,
        'normalized_provider': normalized_provider,
        'normalized_currency': normalized_currency,
        'rate_value': Decimal(str(rate_value)).quantize(Decimal('0.0001')) if (is_valid and rate_value is not None) else None,
        'is_valid': is_valid,
        'validation_errors': errors,
    }

    return cleaned
