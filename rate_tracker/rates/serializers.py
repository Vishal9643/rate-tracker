"""
DRF serializers for Rate-Tracker API.
"""
from decimal import Decimal

from rest_framework import serializers

from rates.models import Rate
from rates.services.data_cleaner import VALID_RATE_TYPES


VALID_RATE_TYPE_LIST = sorted(list(VALID_RATE_TYPES))


class RateLatestSerializer(serializers.Serializer):
    """
    Output serializer for GET /rates/latest/
    Works with values() dicts from the query.
    """
    provider = serializers.CharField(source='provider__normalized_name')
    rate_type = serializers.CharField()
    rate_value = serializers.DecimalField(max_digits=10, decimal_places=4)
    effective_date = serializers.DateField()
    currency = serializers.CharField()
    last_updated = serializers.DateTimeField(source='ingestion_ts')


class RateHistorySerializer(serializers.ModelSerializer):
    """
    Output serializer for GET /rates/history/
    """
    class Meta:
        model = Rate
        fields = ['rate_value', 'effective_date', 'ingestion_ts']


class RateIngestSerializer(serializers.Serializer):
    """
    Input serializer for POST /rates/ingest/
    Validates strictly — returns structured 400 errors on failure.
    """
    provider = serializers.CharField(max_length=255)
    rate_type = serializers.ChoiceField(
        choices=VALID_RATE_TYPE_LIST,
        error_messages={
            'invalid_choice': (
                f"Invalid rate type. Must be one of: {', '.join(VALID_RATE_TYPE_LIST)}"
            )
        }
    )
    rate_value = serializers.DecimalField(max_digits=10, decimal_places=4)
    effective_date = serializers.DateField()
    source_url = serializers.URLField(required=False, allow_blank=True, default='')
    currency = serializers.CharField(max_length=10, default='USD')

    def validate_rate_value(self, value: Decimal) -> Decimal:
        if value < 0 or value > 20:
            raise serializers.ValidationError(
                'Rate value must be between 0 and 20.'
            )
        return value

    def validate_provider(self, value: str) -> str:
        return value.strip()

    def validate_currency(self, value: str) -> str:
        from rates.services.data_cleaner import normalize_currency
        return normalize_currency(value.strip())


class RateIngestResponseSerializer(serializers.ModelSerializer):
    """
    Output serializer for successful POST /rates/ingest/ response.
    """
    provider = serializers.CharField(source='provider.normalized_name')

    class Meta:
        model = Rate
        fields = ['id', 'provider', 'rate_type', 'rate_value', 'effective_date', 'currency', 'created_at']
