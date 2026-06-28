# Data Quality Analysis Report

## Source File

- **File**: `rates_seed.parquet`
- **Format**: Snappy-compressed Parquet
- **Size**: ~34 MB
- **Rows**: 1,005,000
- **Columns**: 8
- **Row Groups**: 21 (~48K rows each)

## Schema

| Column | Arrow Type | Pandas Type | Nullable |
|--------|-----------|-------------|----------|
| `provider` | string | str | No |
| `rate_type` | string | str | No |
| `rate_value` | double | float64 | **Yes (200 nulls)** |
| `effective_date` | date32[day] | object (date) | No |
| `ingestion_ts` | timestamp[us] | datetime64[us] | No |
| `source_url` | string | str | No |
| `raw_response_id` | string | str | No (all unique UUIDs) |
| `currency` | string | str | No |

## Data Quality Issues

### Issue 1: Provider Name Casing (100,387 rows)

HSBC appears in three different casings. All other providers are consistent.

| Variant | Count |
|---------|-------|
| `HSBC` | 33,767 |
| `Hsbc` | 33,484 |
| `hsbc` | 33,136 |

**Total HSBC rows**: 100,387

**All providers after normalization (10 unique)**:
| Provider | Count |
|----------|-------|
| PNC Bank | 100,897 |
| Citibank | 100,809 |
| Bank of America | 100,789 |
| Wells Fargo | 100,653 |
| Chase | 100,535 |
| Truist | 100,522 |
| Capital One | 100,488 |
| HSBC | 100,387 |
| US Bancorp | 100,156 |
| TD Bank | 99,764 |

### Issue 2: Currency Inconsistency (20,211 rows)

| Value | Count |
|-------|-------|
| `USD` | 984,789 |
| `usd` | 10,120 |
| `US Dollar` | 10,091 |

**Resolution**: Normalize all to `USD`.

### Issue 3: Null Rate Values (200 rows)

200 rows have `rate_value` as NULL. These cannot be stored as valid rates.

**Resolution**: Skip these rows, mark raw_response as `failed`, log warning.

### Issue 4: Negative Rates (15 rows)

| Row Index | Provider | Rate Type | Rate Value |
|-----------|----------|-----------|------------|
| 52362 | Truist | savings_easy_access | -1.7301 |
| 120959 | Capital One | 30yr_fixed_mortgage | -1.2536 |
| 233902 | Truist | 5yr_arm_mortgage | -0.7537 |
| 402723 | Hsbc | savings_1yr_fixed | -0.8249 |
| 407779 | Citibank | savings_easy_access | -1.7021 |
| 418556 | HSBC | 30yr_fixed_mortgage | -1.7121 |
| 462019 | Citibank | 5yr_arm_mortgage | -1.8440 |
| 519337 | Citibank | 5yr_arm_mortgage | -0.0354 |
| 538652 | PNC Bank | savings_1yr_fixed | -1.1396 |
| 539681 | PNC Bank | savings_1yr_fixed | -0.0903 |
| (+ 5 more) | | | |

**Resolution**: Skip these rows, mark raw_response as `failed`, log warning. Negative mortgage/savings rates are not realistic in this dataset.

### Issue 5: Extreme High Rates (>20%) — 15 rows

| Row Index | Provider | Rate Type | Rate Value |
|-----------|----------|-----------|------------|
| 34163 | Truist | savings_easy_access | 72.93% |
| 130986 | hsbc | savings_1yr_fixed | 66.25% |
| 376428 | PNC Bank | 15yr_fixed_mortgage | 66.91% |
| 422892 | Citibank | 30yr_fixed_mortgage | 70.19% |
| 468849 | Wells Fargo | 30yr_fixed_mortgage | 91.46% |
| 503928 | Chase | savings_1yr_fixed | 54.75% |
| 651416 | Chase | 5yr_arm_mortgage | 51.23% |
| 729051 | PNC Bank | 15yr_fixed_mortgage | 95.96% |
| 767230 | Truist | 30yr_fixed_mortgage | 53.39% |
| 784120 | Truist | 5yr_arm_mortgage | 97.39% |
| (+ 5 more) | | | |

**Resolution**: Skip these rows. Current US rates range 3-10%. 20% is an extremely generous upper bound. Values like 97% are clearly corrupt data.

### Issue 6: Date Mismatches (50 rows)

50 rows have `effective_date` significantly different from `ingestion_ts`:
- `effective_date` is in the future (e.g., 2026-09-22)
- `ingestion_ts` is in the past (e.g., 2025-01-05)
- These same 50 rows have `effective_date > 2026-03-26` (the last ingestion timestamp)

Example:
```
Provider: Chase, effective_date: 2026-09-13, ingestion_ts: 2025-01-05
Provider: TD Bank, effective_date: 2026-07-12, ingestion_ts: 2024-10-08
```

**Resolution**: Ingest these records but log a warning. The data could represent forward-dated rate announcements. The raw_response preserves the original data.

### Summary of Data Quality Issues

| Issue | Affected Rows | Action | Data Lost |
|-------|---------------|--------|-----------|
| Provider casing | 100,387 | Normalize | 0 |
| Currency inconsistency | 20,211 | Normalize | 0 |
| Null rate_value | 200 | Skip + log | 200 |
| Negative rates | 15 | Skip + log | 15 |
| Extreme rates (>20%) | 15 | Skip + log | 15 |
| Date mismatches | 50 | Ingest + warn | 0 |
| **Total rows skipped** | | | **230** |
| **Total rows ingested** | | | **~1,004,770** |

## Rate Value Distribution by Type

| Rate Type | Mean | Std Dev | Min (valid) | Max (valid) |
|-----------|------|---------|-------------|-------------|
| savings_easy_access | 4.50% | 0.61 | ~2.5% | ~6.5% |
| savings_1yr_fixed | 5.00% | 0.63 | ~3.0% | ~7.0% |
| 5yr_arm_mortgage | 6.00% | 0.92 | ~3.5% | ~8.5% |
| 15yr_fixed_mortgage | 6.30% | 0.90 | ~3.5% | ~9.0% |
| 30yr_fixed_mortgage | 7.00% | 0.91 | ~4.5% | ~10.0% |

## Source URLs

50 unique source URLs, following the pattern:
```
https://www.{provider-slug}.com/rates/{rate_type}
```

Each provider×rate_type combination has exactly one source URL pattern, with ~20K rows each.
