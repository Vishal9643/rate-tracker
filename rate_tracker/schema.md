# Schema Documentation

## Overview

The Rate-Tracker database has four tables. The design prioritises:
1. **Idempotency** — the same data can be ingested multiple times without duplicates
2. **Query efficiency** — the three required queries are each served by a dedicated index
3. **Auditability** — raw data is preserved even when validation fails

---

## Table: `providers`

Lookup table that normalises provider names.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | BIGINT | PK, AUTO | Surrogate key |
| `name` | VARCHAR(255) | UNIQUE, INDEX | Original ingested provider name (e.g., `hsbc`) |
| `normalized_name` | VARCHAR(255) | INDEX | Canonical form (e.g., `HSBC`) |
| `created_at` | TIMESTAMPTZ | NOT NULL | Record creation time |

**Why a separate lookup table?** The parquet data shows HSBC in three casings (100,387 rows). A lookup table with `normalized_name` solves this at the data layer. All API responses use `normalized_name`. Future enrichment (logos, status flags, display names) can be added without touching the `rates` table.

**Alternative considered**: Inline normalization in the `rates` table (a `VARCHAR normalized_provider` column). Rejected because it would duplicate provider metadata across every rate row and make provider-level queries messier.

---

## Table: `ingestion_jobs`

Tracks each invocation of the ingestion pipeline.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Job identifier (UUID for global uniqueness) |
| `status` | VARCHAR(20) | INDEX | One of: `started`, `processing`, `completed`, `failed` |
| `source_file` | VARCHAR(500) | | Path to source file |
| `total_rows` | INTEGER | | Total rows in source |
| `processed_rows` | INTEGER | | Rows successfully inserted |
| `failed_rows` | INTEGER | | Rows that failed validation |
| `skipped_rows` | INTEGER | | Rows skipped by idempotency constraint |
| `error_message` | TEXT | | Set if job status is `failed` |
| `started_at` | TIMESTAMPTZ | AUTO | Job start time |
| `completed_at` | TIMESTAMPTZ | NULLABLE | Job end time |

**Index**: `(status, started_at)` — for querying recent failed jobs.

---

## Table: `raw_responses`

Stores the raw input data before cleaning. Required by spec: *"Store raw responses alongside cleaned records so failed parses can be replayed."*

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Internal ID |
| `raw_response_id` | VARCHAR(255) | UNIQUE, INDEX | UUID from source data — prevents duplicate raw records on re-run |
| `raw_data` | JSONB | NOT NULL | Full original row as JSON |
| `source_url` | VARCHAR(500) | | Origin URL |
| `ingestion_job_id` | UUID | FK → ingestion_jobs | Links raw record to its job |
| `status` | VARCHAR(20) | INDEX | One of: `pending`, `processed`, `failed` |
| `error_message` | TEXT | | Set when validation fails |
| `created_at` | TIMESTAMPTZ | AUTO | Record creation time |

**Why store raw data?** If parsing logic changes (e.g., we decide the 20% threshold was wrong), we can reprocess `failed` raw responses without re-reading the parquet file. The `raw_response_id` field (the UUID from the parquet) guarantees idempotent raw storage.

**Index**: `(status, created_at)` — for finding records eligible for replay (`WHERE status = 'failed'`).

---

## Table: `rates`

The cleaned, normalised rate records. This is the primary query target.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | BIGINT | PK, AUTO | Surrogate key (BigInt for 1M+ row future-proofing) |
| `provider_id` | BIGINT | FK → providers, NOT NULL | Provider FK |
| `rate_type` | VARCHAR(50) | INDEX | e.g., `30yr_fixed_mortgage` |
| `rate_value` | DECIMAL(10,4) | NOT NULL | Interest rate (exact decimal, not float) |
| `effective_date` | DATE | INDEX | When the rate became effective |
| `currency` | VARCHAR(10) | DEFAULT 'USD' | Normalised currency code |
| `raw_response_id` | UUID | FK → raw_responses, NULLABLE | Traceability to raw data |
| `source_url` | VARCHAR(500) | | Source URL |
| `ingestion_ts` | TIMESTAMPTZ | NOT NULL | Original timestamp from source |
| `created_at` | TIMESTAMPTZ | AUTO | DB insert time |

**Unique constraint**: `(provider_id, rate_type, effective_date, ingestion_ts)` — the idempotency key. Running `seed_data` twice produces identical row counts.

**Why DecimalField not FloatField?** IEEE-754 floating-point arithmetic causes rounding errors for financial values. `DECIMAL(10, 4)` gives exact representation (e.g., `6.7500` not `6.7500000000001`).

**Why BigAutoField?** With 1M rows at ingestion and scheduled hourly updates, a standard 32-bit integer (2.1B ceiling) would overflow in ~200 years of hourly updates. BigInt costs 4 extra bytes per row — negligible at this scale.

**Why SET_NULL on raw_response FK?** Raw responses can be purged for storage management. `SET_NULL` preserves the clean rate data even after raw response cleanup. The traceability column becomes `NULL` rather than causing a cascade delete.

### Indexes

| Index Name | Columns | Serves Query |
|------------|---------|--------------|
| `idx_rate_provider_type` | `(provider_id, rate_type)` | Latest rate per provider (`DISTINCT ON`) |
| `idx_rate_type_date` | `(rate_type, effective_date)` | Rate change over last 30 days for a given type |
| `idx_rate_created_at` | `(created_at)` | All records ingested in a given 24-hour window |
| `idx_rate_provider_type_date` | `(provider_id, rate_type, effective_date)` | History: provider + type + date range |
| `uq_rate_provider_type_date_ts` | `(provider_id, rate_type, effective_date, ingestion_ts)` | Idempotency unique constraint |

**Tradeoff on indexes**: Five indexes on the `rates` table increases write overhead at ingestion time (bulk inserts must update each index). For a read-heavy API serving millions of reads vs. infrequent batch writes, this is the correct tradeoff. If write throughput became a bottleneck, we could defer index creation until after bulk load using `CREATE INDEX CONCURRENTLY`.
