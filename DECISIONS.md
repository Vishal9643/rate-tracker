# DECISIONS.md

Engineering decisions made during this Rate-Tracker implementation.

---

## 1. Assumptions

**Data characteristics:**
- The `rates_seed.parquet` file is Snappy-compressed and contains exactly 1,005,000 rows with 8 columns. The file was treated as the authoritative source of truth for the schema design.
- HSBC appearing as `HSBC`, `Hsbc`, and `hsbc` (100,387 rows) is a data quality issue, not intentional variant data. All three map to `HSBC` in the provider normalization table.
- Records with `rate_value > 20%` (97.39% being the max observed) are corrupt data, not legitimate rates. Current US mortgage rates range 3–10%; 20% is a generous upper bound.
- Negative rate values (–1.84 being the minimum) are data errors. While negative central bank rates exist in some economies, they don't apply to US retail mortgage/savings products.
- The 50 records with `effective_date` significantly after `ingestion_ts` (up to 2026-09-22) are ingested with a warning log but not rejected — they may be legitimate forward-dated rate announcements.

**Environment constraints:**
- The application is expected to run via Docker Compose with `docker-compose up` requiring no host-level configuration beyond copying `.env.example`.
- The reviewer runs on a machine with Docker installed. No PostgreSQL, Redis, or Python is required on the host.
- The seed file (`rates_seed.parquet`) is expected in the project root when running `python manage.py seed_data` without `--file` argument.

**Use case assumptions:**
- The API is read-heavy. The `/rates/latest/` endpoint is cached because it will be called most frequently (dashboard auto-refresh every 60 seconds).
- The ingest webhook is called infrequently (batch/scheduled pattern), so cache invalidation on write is acceptable — no write-through cache needed.

---

## 2. Idempotency Strategy

The seed file contains multiple data issues. Here is exactly how the ingestion worker handles repeated runs:

**Problem**: Running `python manage.py seed_data` twice should not double the row count.

**Solution: Four-layer idempotency**

1. **Row-level (primary mechanism)**: A composite `UniqueConstraint` on `(provider_id, rate_type, effective_date, ingestion_ts)` is defined in the `Rate` model. On bulk insert, `bulk_create(ignore_conflicts=True)` is used, which translates to `INSERT ... ON CONFLICT DO NOTHING`. Duplicate rows are skipped silently — no error, no retry, no pre-check query.

2. **Provider-level**: `Provider` has a `UNIQUE` constraint on `normalized_name`. The ingestion service uses `get_or_create(normalized_name=...)` to ensure no duplicate provider records regardless of re-runs.

3. **Raw response-level**: `RawResponse` has a `UNIQUE` constraint on `raw_response_id` (the UUID from the parquet file). Re-ingesting the same file won't create duplicate raw response audit records.

4. **Job-level**: Each `seed_data` invocation creates a new `IngestionJob`. If a previous run failed, the new run re-processes the entire file. The unique constraints catch any valid records already written; the `skipped_rows` counter reports how many were duplicates.

**Observed output:**
```
# First run:
IngestionJob <id>: 1,005,000 total, ~1,004,770 processed, 230 failed, 0 skipped

# Second run (all valid records already exist):
IngestionJob <id>: 1,005,000 total, 0 processed, 230 failed, ~1,004,770 skipped
```

**Data issues handled:**
- Null `rate_value` (200 rows): stored in `RawResponse` with `status='failed'` and `error_message='rate_value is null'`. Not inserted into `Rate`.
- Negative rates (15 rows): same — stored as failed raw response, not inserted.
- Extreme rates >20% (15 rows): same treatment.
- Provider casing (100,387 rows): normalized to canonical form before insert. `HSBC`, `Hsbc`, `hsbc` all become a single `Provider(normalized_name='HSBC')` record.
- Currency variants (20,211 rows): `usd`, `US Dollar` → `USD` before insert.
- Date mismatches (50 rows): ingested successfully with a `WARNING` log entry. Not rejected.

---

## 3. One Conscious Tradeoff: Celery Beat over Cron

**Decision**: Use Celery Beat (`django_celery_beat.schedulers:DatabaseScheduler`) for scheduled ingestion, not a host-level cron job.

**Option A (chosen): Celery Beat**
- Runs inside the Docker Compose stack — no host access required
- Schedule is configurable via Django admin UI at runtime
- History and retry logic available via Celery
- Consistent with the Celery worker already required for async tasks

**Option B (rejected): Host cron + management command**
- Simpler — just `0 * * * * python manage.py seed_data`
- Requires SSH access to the host or a bind-mounted crontab
- Not portable across Docker/Kubernetes/AWS without extra tooling
- No retry on failure

**Why this matters in a 48-hour window**: Celery Beat adds one service to docker-compose and one settings entry. The overhead is minimal and the portability benefit is significant for a production-shaped assessment. If I had more time I would have added Flower for Celery task monitoring.

---

## 4. One Thing I Would Change With More Time

**Replace 60-second polling with WebSocket push via Django Channels.**

Currently the Next.js dashboard uses SWR with `refreshInterval: 60000` — every 60 seconds it fires a `GET /rates/latest/` request. This means:
- Up to 59 seconds of stale data displayed
- N clients × 1 request/minute = unnecessary server load
- No indicator to the user when a rate actually changes

**What I would build instead**: Django Channels + Redis Channel Layer + WebSocket connection from the Next.js client. When the Celery ingestion job completes, it publishes a `rates.updated` event to a Redis channel. The Django Channels consumer broadcasts this to all connected WebSocket clients. The frontend updates immediately — zero polling delay, zero wasted requests.

The client code would look like:
```typescript
const ws = new WebSocket('ws://localhost:8000/ws/rates/');
ws.onmessage = () => mutate(); // SWR revalidation on push
```

This is the kind of change that would meaningfully improve perceived responsiveness in a production product. The 48-hour constraint made it the right tradeoff to defer — SWR polling achieves the spec requirement (`auto-refresh every 60 seconds — without a full page reload`) with zero additional infrastructure.
