"""
Data models for Rate-Tracker.

Models:
- Provider     : Lookup table normalising provider names (handles HSBC/Hsbc/hsbc)
- IngestionJob : Tracks each ingestion run for observability
- RawResponse  : Stores raw ingested data for replay / debugging
- Rate         : Cleaned, normalised rate records (core table)
"""
import uuid
from django.db import models


class Provider(models.Model):
    """
    Canonical provider registry.
    `name` stores the original ingested name; `normalized_name` is the canonical form.
    Using a lookup table allows future enrichment (logos, URLs, status flags)
    and keeps JOIN semantics clean.
    """
    name = models.CharField(max_length=255, unique=True, db_index=True)
    normalized_name = models.CharField(max_length=255, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'providers'
        ordering = ['normalized_name']

    def __str__(self) -> str:
        return self.normalized_name


class IngestionJob(models.Model):
    """
    One record per invocation of seed_data or scheduled ingestion.
    Enables audit trail: how many rows succeeded, failed, were skipped as duplicates.
    """
    STATUS_CHOICES = [
        ('started', 'Started'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='started', db_index=True)
    source_file = models.CharField(max_length=500, blank=True)
    total_rows = models.IntegerField(default=0)
    processed_rows = models.IntegerField(default=0)
    failed_rows = models.IntegerField(default=0)
    skipped_rows = models.IntegerField(default=0)  # duplicates caught by unique constraint
    error_message = models.TextField(blank=True, default='')

    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'ingestion_jobs'
        indexes = [
            models.Index(fields=['status', 'started_at'], name='idx_job_status_started'),
        ]
        ordering = ['-started_at']

    def __str__(self) -> str:
        return f"IngestionJob {self.id} [{self.status}]"


class RawResponse(models.Model):
    """
    Stores the raw input data before cleaning/validation.
    Required by spec: "Store raw responses alongside cleaned records so failed parses
    can be replayed."
    Status transitions: pending → processed | failed
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processed', 'Processed'),
        ('failed', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    raw_response_id = models.CharField(max_length=255, unique=True, db_index=True)
    raw_data = models.JSONField()
    source_url = models.URLField(max_length=500)
    ingestion_job = models.ForeignKey(
        IngestionJob,
        on_delete=models.CASCADE,
        related_name='raw_responses',
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True,
    )
    error_message = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'raw_responses'
        indexes = [
            models.Index(fields=['status', 'created_at'], name='idx_raw_status_created'),
        ]
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f"RawResponse {self.raw_response_id} [{self.status}]"


class Rate(models.Model):
    """
    Cleaned, normalised interest-rate record.

    Idempotency: The composite UniqueConstraint on (provider, rate_type,
    effective_date, ingestion_ts) means running seed_data multiple times is safe —
    duplicate rows are silently skipped via bulk_create(ignore_conflicts=True).

    BigAutoField PK: 1M+ rows and growing; standard int (2.1B ceiling) is fine
    today but BigInt is future-proof at negligible cost.

    DecimalField for rate_value: Financial data must not use float arithmetic
    (IEEE-754 rounding errors). Decimal gives exact representation.
    """
    id = models.BigAutoField(primary_key=True)
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='rates')
    rate_type = models.CharField(max_length=50, db_index=True)
    rate_value = models.DecimalField(max_digits=10, decimal_places=4)
    effective_date = models.DateField(db_index=True)
    currency = models.CharField(max_length=10, default='USD')

    # Traceability back to raw input — SET_NULL so purging raw_responses
    # doesn't destroy clean rate data
    raw_response = models.ForeignKey(
        RawResponse,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='rates',
    )
    source_url = models.URLField(max_length=500, blank=True)

    # ingestion_ts preserved from source (not auto-generated)
    ingestion_ts = models.DateTimeField(
        help_text="Original ingestion timestamp from source data"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'rates'
        constraints = [
            # Idempotency key: same provider + type + date + ts = same record
            models.UniqueConstraint(
                fields=['provider', 'rate_type', 'effective_date', 'ingestion_ts'],
                name='uq_rate_provider_type_date_ts',
            ),
        ]
        indexes = [
            # "Latest rate per provider" — DISTINCT ON (provider, rate_type) ORDER BY ...
            models.Index(
                fields=['provider', 'rate_type'],
                name='idx_rate_provider_type',
            ),
            # "Rate change over last 30 days for a given type"
            models.Index(
                fields=['rate_type', 'effective_date'],
                name='idx_rate_type_date',
            ),
            # "All records ingested in a given 24-hour window"
            models.Index(
                fields=['created_at'],
                name='idx_rate_created_at',
            ),
            # "History: provider + type + date range" (API endpoint)
            models.Index(
                fields=['provider', 'rate_type', 'effective_date'],
                name='idx_rate_provider_type_date',
            ),
        ]
        ordering = ['-effective_date', '-ingestion_ts']

    def __str__(self) -> str:
        return f"{self.provider} {self.rate_type} {self.rate_value}% ({self.effective_date})"
