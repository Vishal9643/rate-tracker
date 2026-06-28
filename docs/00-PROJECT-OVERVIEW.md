# Rate-Tracker: Project Overview

## What This Is

A **Senior Full-Stack Developer take-home assessment** for Forbes Advisor / Marketplace Data Research Engineering Team.

**Time constraint**: 48 hours. All tools permitted (AI included — they want to see you understand what it produced).

## What We're Building

A production-shaped application that **ingests, stores, exposes, and visualises interest-rate data** (mortgage & savings rates from financial providers).

The pipeline:
```
data acquired → cleaned & persisted → surfaced via typed API → rendered in browser → refreshed automatically
```

## Evaluation Criteria (What They Actually Care About)

1. **Senior judgment** — what you chose to build first and what you deliberately deferred
2. **Visible thinking** — assumptions, tradeoffs, decisions documented as you go
3. **Idempotency and observability** — as first-class concerns, not afterthoughts
4. **Honest tool use** — understand what AI tools produce

## Required Deliverables

### Code
| Phase | Scope | Required? |
|-------|-------|-----------|
| Phase 1 | Data acquisition & persistence (scraper, DB, scheduler) | ✅ Required |
| Phase 2 | Django REST API (3 endpoints, auth, tests) | ✅ Required |
| Phase 3 | NextJS frontend dashboard | ⭐ Optional bonus |
| Phase 4A | Docker Compose (full stack) | ✅ Required |
| Phase 4B | Environment & secrets discipline | ✅ Required |
| Phase 4C | Observability stub (structured logging) | ⭐ Optional bonus |

### Documentation
| File | Purpose | Required? |
|------|---------|-----------|
| `README.md` | Prerequisites, run instructions, test instructions, architectural rationale | ✅ Required |
| `DECISIONS.md` | Assumptions, idempotency strategy, tradeoff, improvement | ✅ Required |
| `schema.md` | Table design, indexes, tradeoffs | ✅ Required |

### Submission
- Private GitHub repo with collaborator access
- Screen recording (Loom/Google Drive) showing full running application
- Must start cleanly with `docker-compose up`
- Dashboard accessible at `localhost:3000` within 2 minutes

## The Seed Data

File: `rates_seed.parquet` (~34 MB, Snappy-compressed, ~1,005,000 rows, 8 columns)

### Schema
| Column | Type | Description |
|--------|------|-------------|
| `provider` | string | Financial institution name |
| `rate_type` | string | Type of financial rate |
| `rate_value` | double | The rate percentage |
| `effective_date` | date32 | When the rate became effective |
| `ingestion_ts` | timestamp | When the record was ingested |
| `source_url` | string | URL of the source |
| `raw_response_id` | string (UUID) | Unique ID for the raw response |
| `currency` | string | Currency code |

### Data Quality Issues (Intentional — Part of the Assessment!)
| Issue | Count | Details |
|-------|-------|---------|
| Provider casing inconsistency | 100,387 rows | `HSBC`, `Hsbc`, `hsbc` should all be same provider |
| Currency inconsistency | 20,211 rows | `USD`, `usd`, `US Dollar` |
| Null rate values | 200 rows | `rate_value` is NULL |
| Negative rates | 15 rows | e.g., -1.844 |
| Extreme rates (>20%) | 15 rows | e.g., 97.39% — clearly outliers |
| Mismatched dates | 50 rows | `effective_date` far in future vs `ingestion_ts` |
| Future effective dates | 50 rows | Dates beyond last ingestion timestamp |

### Providers (10 unique after normalization)
Bank of America, Capital One, Chase, Citibank, HSBC, PNC Bank, TD Bank, Truist, US Bancorp, Wells Fargo

### Rate Types (5)
`15yr_fixed_mortgage`, `30yr_fixed_mortgage`, `5yr_arm_mortgage`, `savings_1yr_fixed`, `savings_easy_access`

### Date Range
- Effective dates: 2024-09-25 to 2026-09-22
- Ingestion timestamps: 2024-09-25 to 2026-03-26
