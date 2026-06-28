# Database Schema Design

## Models

### 1. `Provider` (Lookup Table)

Normalizes provider names to handle casing issues (`HSBC`/`Hsbc`/`hsbc`).

```python
class Provider(models.Model):
    name = models.CharField(max_length=255, unique=True, db_index=True)
    # Canonical normalized name (e.g., "HSBC")
    normalized_name = models.CharField(max_length=255, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'providers'
```

**Rationale**: A provider lookup table with `normalized_name` handles the HSBC casing problem at the data layer. Queries can join on `normalized_name` when aggregating, while preserving the original ingested name.

**Alternative considered**: Just normalizing inline in the Rate table. Rejected because having a lookup table lets us add provider metadata later (logo, URL, status) and makes the API cleaner.

---

### 2. `RawResponse` (Audit Trail)

Stores raw ingested data for replay/debugging. Required by spec: *"Store raw responses alongside cleaned records so failed parses can be replayed."*

```python
class RawResponse(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    raw_response_id = models.CharField(max_length=255, unique=True, db_index=True)
    # The original raw data as JSON
    raw_data = models.JSONField()
    source_url = models.URLField(max_length=500)
    ingestion_job = models.ForeignKey('IngestionJob', on_delete=models.CASCADE, related_name='raw_responses', null=True)
    # Processing status
    status = models.CharField(
        max_length=20,
        choices=[('pending', 'Pending'), ('processed', 'Processed'), ('failed', 'Failed')],
        default='pending',
        db_index=True
    )
    error_message = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'raw_responses'
        indexes = [
            models.Index(fields=['status', 'created_at'], name='idx_raw_status_created'),
        ]
```

**Rationale**: Each raw response gets stored before parsing. If parsing fails, the `status` is set to `failed` with `error_message`. A replay mechanism can re-process `pending` or `failed` records without re-fetching.

---

### 3. `Rate` (Core Table)

The cleaned, normalized rate records.

```python
class Rate(models.Model):
    id = models.BigAutoField(primary_key=True)
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='rates')
    rate_type = models.CharField(max_length=50, db_index=True)
    rate_value = models.DecimalField(max_digits=10, decimal_places=4)
    effective_date = models.DateField(db_index=True)
    currency = models.CharField(max_length=10, default='USD')

    # Traceability back to raw data
    raw_response = models.ForeignKey(RawResponse, on_delete=models.SET_NULL, null=True, related_name='rates')
    source_url = models.URLField(max_length=500, blank=True)

    # Timestamps
    ingestion_ts = models.DateTimeField(help_text="Original ingestion timestamp from source")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'rates'
        # Composite unique constraint for idempotency
        constraints = [
            models.UniqueConstraint(
                fields=['provider', 'rate_type', 'effective_date', 'ingestion_ts'],
                name='uq_rate_provider_type_date_ts'
            ),
        ]
        indexes = [
            # Query: Latest rate per provider (ORDER BY effective_date DESC, ingestion_ts DESC)
            models.Index(fields=['provider', 'rate_type', '-effective_date', '-ingestion_ts'],
                        name='idx_rate_latest'),
            # Query: Rate change over last 30 days for a given type
            models.Index(fields=['rate_type', 'effective_date'],
                        name='idx_rate_type_date'),
            # Query: All records ingested in a given 24-hour window
            models.Index(fields=['created_at'],
                        name='idx_rate_created_at'),
            # Query: History by provider + type + date range
            models.Index(fields=['provider', 'rate_type', 'effective_date'],
                        name='idx_rate_provider_type_date'),
        ]
```

**Key design decisions**:

1. **`DecimalField` not `FloatField`**: Financial rates need exact decimal representation. Float arithmetic causes rounding errors.

2. **Composite unique constraint** (`provider + rate_type + effective_date + ingestion_ts`): This is the **idempotency key**. Running `seed_data` multiple times won't create duplicate rows — `INSERT ... ON CONFLICT DO NOTHING` will skip existing records.

3. **`BigAutoField` primary key**: With 1M+ rows and growing, standard int could overflow. BigAutoField is future-proof.

4. **`SET_NULL` on raw_response FK**: If raw responses are purged for storage, we don't lose the cleaned rates.

---

### 4. `IngestionJob` (Job Tracking)

Tracks each ingestion run for observability.

```python
class IngestionJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    status = models.CharField(
        max_length=20,
        choices=[
            ('started', 'Started'),
            ('processing', 'Processing'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
        ],
        default='started',
        db_index=True
    )
    source_file = models.CharField(max_length=500, blank=True)
    total_rows = models.IntegerField(default=0)
    processed_rows = models.IntegerField(default=0)
    failed_rows = models.IntegerField(default=0)
    skipped_rows = models.IntegerField(default=0)  # duplicates skipped by idempotency
    error_message = models.TextField(blank=True, default='')

    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'ingestion_jobs'
        indexes = [
            models.Index(fields=['status', 'started_at'], name='idx_job_status_started'),
        ]
```

---

## Index Strategy & Query Optimization

### Required Queries from Spec

#### 1. "Latest rate per provider"
```sql
-- Uses idx_rate_latest (provider, rate_type, effective_date DESC, ingestion_ts DESC)
SELECT DISTINCT ON (r.provider_id, r.rate_type)
    p.normalized_name, r.rate_type, r.rate_value, r.effective_date
FROM rates r
JOIN providers p ON r.provider_id = p.id
ORDER BY r.provider_id, r.rate_type, r.effective_date DESC, r.ingestion_ts DESC;
```

#### 2. "Rate change over last 30 days for a given type"
```sql
-- Uses idx_rate_type_date (rate_type, effective_date)
SELECT p.normalized_name, r.rate_value, r.effective_date
FROM rates r
JOIN providers p ON r.provider_id = p.id
WHERE r.rate_type = %s
  AND r.effective_date >= CURRENT_DATE - INTERVAL '30 days'
ORDER BY r.effective_date;
```

#### 3. "All records ingested in a given 24-hour window"
```sql
-- Uses idx_rate_created_at (created_at)
SELECT * FROM rates
WHERE created_at >= %s AND created_at < %s + INTERVAL '24 hours';
```

#### 4. "History: provider + type + date range" (for API)
```sql
-- Uses idx_rate_provider_type_date (provider, rate_type, effective_date)
SELECT r.rate_value, r.effective_date
FROM rates r
WHERE r.provider_id = %s
  AND r.rate_type = %s
  AND r.effective_date BETWEEN %s AND %s
ORDER BY r.effective_date;
```

## ERD

```
┌─────────────────┐       ┌──────────────────────┐
│    Provider      │       │    IngestionJob       │
├─────────────────┤       ├──────────────────────┤
│ id (PK)         │       │ id (UUID PK)         │
│ name            │       │ status               │
│ normalized_name │       │ source_file          │
│ created_at      │       │ total_rows           │
└────────┬────────┘       │ processed_rows       │
         │                │ failed_rows          │
         │ 1:N            │ skipped_rows         │
         │                │ error_message        │
         ▼                │ started_at           │
┌─────────────────┐       │ completed_at         │
│      Rate       │       └──────────┬───────────┘
├─────────────────┤                  │
│ id (BigAuto PK) │                  │ 1:N
│ provider_id(FK) │                  │
│ rate_type       │       ┌──────────▼───────────┐
│ rate_value      │       │    RawResponse       │
│ effective_date  │       ├──────────────────────┤
│ currency        │       │ id (UUID PK)         │
│ raw_response(FK)│──────▶│ raw_response_id      │
│ source_url      │       │ raw_data (JSON)      │
│ ingestion_ts    │       │ source_url           │
│ created_at      │       │ ingestion_job_id(FK) │
└─────────────────┘       │ status               │
                          │ error_message        │
                          │ created_at           │
                          └──────────────────────┘
```
