# Frontend Design (Next.js Dashboard)

## Overview

Phase 3 is optional bonus but implementing it demonstrates full-stack capability. The dashboard connects to the real Django API — no hardcoded data.

## Tech Stack

| Concern | Choice | Rationale |
|---------|--------|-----------|
| Framework | Next.js 14 (App Router) | Required by spec |
| Data Fetching | SWR | Auto-refresh, caching, loading/error states built-in |
| Charting | Recharts | Lightweight, React-native, responsive |
| Styling | CSS Modules + CSS custom properties | No extra deps, performant |
| HTTP Client | fetch (native) | No axios needed for simple GET/POST |

## Pages & Components

### Page: `/` (Dashboard)

The single-page dashboard with two main sections:

#### 1. Rate Comparison Table

**Component**: `RateTable.tsx`

| Provider | Rate Type | Rate | Effective Date | Last Updated |
|----------|-----------|------|----------------|--------------|
| Chase | 30yr Fixed | 6.75% | 2026-03-25 | 2h ago |
| Wells Fargo | 30yr Fixed | 6.82% | 2026-03-25 | 3h ago |

**Features**:
- Sortable by rate value (asc/desc) and last-updated date
- Filter dropdown for rate type
- Loading skeleton while data fetches
- Error state with retry button
- Auto-refresh every 60 seconds (SWR `refreshInterval`)

**Implementation**:
```tsx
// src/components/RateTable.tsx
'use client';

import useSWR from 'swr';
import { useState } from 'react';

type SortField = 'rate_value' | 'effective_date';
type SortOrder = 'asc' | 'desc';

export default function RateTable() {
    const [rateType, setRateType] = useState<string>('');
    const [sortField, setSortField] = useState<SortField>('rate_value');
    const [sortOrder, setSortOrder] = useState<SortOrder>('asc');

    const url = rateType
        ? `/api/v1/rates/latest/?type=${rateType}`
        : '/api/v1/rates/latest/';

    const { data, error, isLoading, mutate } = useSWR(url, fetcher, {
        refreshInterval: 60000,  // 60 seconds auto-refresh
        revalidateOnFocus: true,
    });

    if (isLoading) return <LoadingSkeleton rows={10} />;
    if (error) return <ErrorState message={error.message} onRetry={() => mutate()} />;

    const sorted = sortData(data.data, sortField, sortOrder);

    return (
        <div className={styles.tableContainer}>
            <div className={styles.controls}>
                <select value={rateType} onChange={e => setRateType(e.target.value)}>
                    <option value="">All Types</option>
                    <option value="30yr_fixed_mortgage">30yr Fixed</option>
                    <option value="15yr_fixed_mortgage">15yr Fixed</option>
                    <option value="5yr_arm_mortgage">5yr ARM</option>
                    <option value="savings_1yr_fixed">Savings 1yr</option>
                    <option value="savings_easy_access">Savings Easy Access</option>
                </select>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Provider</th>
                        <th>Rate Type</th>
                        <th onClick={() => toggleSort('rate_value')} className={styles.sortable}>
                            Rate {sortField === 'rate_value' && (sortOrder === 'asc' ? '↑' : '↓')}
                        </th>
                        <th onClick={() => toggleSort('effective_date')} className={styles.sortable}>
                            Last Updated {sortField === 'effective_date' && (sortOrder === 'asc' ? '↑' : '↓')}
                        </th>
                    </tr>
                </thead>
                <tbody>
                    {sorted.map(rate => (
                        <tr key={`${rate.provider}-${rate.rate_type}`}>
                            <td>{rate.provider}</td>
                            <td>{formatRateType(rate.rate_type)}</td>
                            <td className={styles.rateValue}>{rate.rate_value}%</td>
                            <td>{formatDate(rate.effective_date)}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}
```

#### 2. Rate History Chart

**Component**: `RateChart.tsx`

A line chart showing 30-day rate history for a user-selected provider + type.

**Features**:
- Two dropdowns: provider and rate type
- Line chart with Recharts
- Tooltip showing exact rate and date
- Loading state while fetching
- Error state with retry
- Auto-refresh every 60 seconds
- Responsive — works at 375px width

**Implementation**:
```tsx
// src/components/RateChart.tsx
'use client';

import useSWR from 'swr';
import { useState } from 'react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';

export default function RateChart() {
    const [provider, setProvider] = useState('Chase');
    const [rateType, setRateType] = useState('30yr_fixed_mortgage');

    const thirtyDaysAgo = new Date(Date.now() - 30 * 86400000).toISOString().split('T')[0];
    const today = new Date().toISOString().split('T')[0];

    const url = `/api/v1/rates/history/?provider=${provider}&type=${rateType}&from=${thirtyDaysAgo}&to=${today}&page_size=100`;

    const { data, error, isLoading, mutate } = useSWR(url, fetcher, {
        refreshInterval: 60000,
    });

    if (isLoading) return <ChartLoadingSkeleton />;
    if (error) return <ErrorState message={error.message} onRetry={() => mutate()} />;

    return (
        <div className={styles.chartContainer}>
            <div className={styles.controls}>
                <select value={provider} onChange={e => setProvider(e.target.value)}>
                    {PROVIDERS.map(p => <option key={p} value={p}>{p}</option>)}
                </select>
                <select value={rateType} onChange={e => setRateType(e.target.value)}>
                    {RATE_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                </select>
            </div>
            <ResponsiveContainer width="100%" height={400}>
                <LineChart data={data.data}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="effective_date" />
                    <YAxis domain={['auto', 'auto']} />
                    <Tooltip />
                    <Line type="monotone" dataKey="rate_value" stroke="#2563eb" strokeWidth={2} dot={false} />
                </LineChart>
            </ResponsiveContainer>
        </div>
    );
}
```

#### 3. Loading States

**Component**: `LoadingState.tsx`

```tsx
// Skeleton table rows
export function LoadingSkeleton({ rows = 5 }: { rows?: number }) {
    return (
        <div className={styles.skeleton}>
            {Array.from({ length: rows }).map((_, i) => (
                <div key={i} className={styles.skeletonRow}>
                    <div className={styles.skeletonCell} style={{ width: '20%' }} />
                    <div className={styles.skeletonCell} style={{ width: '25%' }} />
                    <div className={styles.skeletonCell} style={{ width: '15%' }} />
                    <div className={styles.skeletonCell} style={{ width: '20%' }} />
                </div>
            ))}
        </div>
    );
}
```

#### 4. Error States

**Component**: `ErrorState.tsx`

```tsx
export function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
    return (
        <div className={styles.errorState}>
            <div className={styles.errorIcon}>⚠️</div>
            <h3>Something went wrong</h3>
            <p>{message}</p>
            <button onClick={onRetry} className={styles.retryButton}>
                Try Again
            </button>
        </div>
    );
}
```

## API Client

```tsx
// src/lib/api.ts
const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export async function fetcher(path: string) {
    const res = await fetch(`${API_BASE}${path}`);

    if (!res.ok) {
        const error = new Error('API request failed');
        error.message = `${res.status}: ${res.statusText}`;
        throw error;
    }

    return res.json();
}
```

## Responsive Layout

The dashboard must be **usable on a 375px-wide viewport** (iPhone SE size).

### Breakpoints
```css
/* Mobile-first approach */
.dashboard {
    padding: 1rem;
    display: flex;
    flex-direction: column;
    gap: 2rem;
}

/* Table scrolls horizontally on mobile */
.tableContainer {
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
}

/* Chart adapts via ResponsiveContainer */

@media (min-width: 768px) {
    .dashboard {
        padding: 2rem;
    }
}

@media (min-width: 1024px) {
    .dashboard {
        max-width: 1200px;
        margin: 0 auto;
        padding: 2rem 3rem;
    }
}
```

## Next.js Configuration

```js
// next.config.js
/** @type {import('next').NextConfig} */
const nextConfig = {
    output: 'standalone',  // For Docker
    async rewrites() {
        return [
            {
                source: '/api/:path*',
                destination: 'http://django:8000/api/:path*',  // Proxy to Django in Docker
            },
        ];
    },
};

module.exports = nextConfig;
```

## Constants

```tsx
// src/lib/constants.ts
export const PROVIDERS = [
    'Bank of America', 'Capital One', 'Chase', 'Citibank',
    'HSBC', 'PNC Bank', 'TD Bank', 'Truist', 'US Bancorp', 'Wells Fargo'
];

export const RATE_TYPES = [
    { value: '30yr_fixed_mortgage', label: '30yr Fixed Mortgage' },
    { value: '15yr_fixed_mortgage', label: '15yr Fixed Mortgage' },
    { value: '5yr_arm_mortgage', label: '5yr ARM Mortgage' },
    { value: 'savings_1yr_fixed', label: 'Savings 1yr Fixed' },
    { value: 'savings_easy_access', label: 'Savings Easy Access' },
];
```
