'use client';
import { useState } from 'react';
import useSWR from 'swr';
import { fetcher } from '@/lib/api';
import { RATE_TYPES, RATE_TYPE_LABELS, AUTO_REFRESH_INTERVAL } from '@/lib/constants';
import { LoadingSkeleton } from './LoadingState';
import { ErrorState } from './ErrorState';
import styles from './RateTable.module.css';

type SortField = 'rate_value' | 'effective_date';
type SortOrder = 'asc' | 'desc';

interface RateItem {
  provider: string;
  rate_type: string;
  rate_value: string;
  effective_date: string;
  currency: string;
  last_updated: string;
}

interface LatestResponse {
  data: RateItem[];
  meta: { count: number; cached: boolean };
}

function sortData(data: RateItem[], field: SortField, order: SortOrder): RateItem[] {
  return [...data].sort((a, b) => {
    let va: string | number = a[field];
    let vb: string | number = b[field];
    if (field === 'rate_value') {
      va = parseFloat(a.rate_value);
      vb = parseFloat(b.rate_value);
    }
    if (va < vb) return order === 'asc' ? -1 : 1;
    if (va > vb) return order === 'asc' ? 1 : -1;
    return 0;
  });
}

function formatDate(d: string) {
  if (!d) return '—';
  const date = new Date(d);
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

export default function RateTable() {
  const [rateType, setRateType] = useState('');
  const [sortField, setSortField] = useState<SortField>('rate_value');
  const [sortOrder, setSortOrder] = useState<SortOrder>('asc');

  const url = rateType
    ? `/api/v1/rates/latest/?type=${rateType}`
    : '/api/v1/rates/latest/';

  const { data, error, isLoading, mutate } = useSWR<LatestResponse>(url, fetcher, {
    refreshInterval: AUTO_REFRESH_INTERVAL,
    revalidateOnFocus: true,
    dedupingInterval: 30_000,
  });

  const toggleSort = (field: SortField) => {
    if (sortField === field) {
      setSortOrder(o => o === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortOrder('asc');
    }
  };

  const sortIcon = (field: SortField) => {
    if (sortField !== field) return <span className={styles.sortIcon}>⇅</span>;
    return <span className={styles.sortIconActive}>{sortOrder === 'asc' ? '↑' : '↓'}</span>;
  };

  if (isLoading) return <LoadingSkeleton rows={10} />;
  if (error) return <ErrorState message={error.message} onRetry={() => mutate()} title="Failed to load rates" />;

  const sorted = sortData(data?.data || [], sortField, sortOrder);

  return (
    <div className={styles.wrapper}>
      <div className={styles.controls}>
        <label htmlFor="rate-type-filter" className={styles.label}>Filter by type</label>
        <select
          id="rate-type-filter"
          value={rateType}
          onChange={e => setRateType(e.target.value)}
          className={styles.select}
          aria-label="Filter by rate type"
        >
          <option value="">All Rate Types</option>
          {RATE_TYPES.map(t => (
            <option key={t.value} value={t.value}>{t.label}</option>
          ))}
        </select>
        {data?.meta?.cached && (
          <span className={styles.cacheBadge} title="Served from cache">
            ⚡ Cached
          </span>
        )}
        <span className={styles.countBadge}>
          {sorted.length} rate{sorted.length !== 1 ? 's' : ''}
        </span>
      </div>

      <div className={styles.tableWrapper}>
        <table className={styles.table} id="rates-table">
          <thead>
            <tr>
              <th className={styles.th}>Provider</th>
              <th className={styles.th}>Rate Type</th>
              <th
                className={`${styles.th} ${styles.sortable}`}
                onClick={() => toggleSort('rate_value')}
                id="sort-rate-value"
                aria-sort={sortField === 'rate_value' ? (sortOrder === 'asc' ? 'ascending' : 'descending') : 'none'}
              >
                Rate {sortIcon('rate_value')}
              </th>
              <th
                className={`${styles.th} ${styles.sortable}`}
                onClick={() => toggleSort('effective_date')}
                id="sort-effective-date"
                aria-sort={sortField === 'effective_date' ? (sortOrder === 'asc' ? 'ascending' : 'descending') : 'none'}
              >
                Effective Date {sortIcon('effective_date')}
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr>
                <td colSpan={4} className={styles.emptyCell}>No rates found for the selected filter.</td>
              </tr>
            ) : (
              sorted.map(rate => (
                <tr key={`${rate.provider}-${rate.rate_type}`} className={styles.tr}>
                  <td className={styles.td}>
                    <span className={styles.providerName}>{rate.provider}</span>
                  </td>
                  <td className={styles.td}>
                    <span className={styles.rateTypeBadge}>
                      {RATE_TYPE_LABELS[rate.rate_type] || rate.rate_type}
                    </span>
                  </td>
                  <td className={`${styles.td} ${styles.rateValue}`}>
                    {parseFloat(rate.rate_value).toFixed(2)}%
                  </td>
                  <td className={`${styles.td} ${styles.dateCell}`}>
                    {formatDate(rate.effective_date)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <p className={styles.refreshNote}>
        Auto-refreshes every 60 seconds
      </p>
    </div>
  );
}
