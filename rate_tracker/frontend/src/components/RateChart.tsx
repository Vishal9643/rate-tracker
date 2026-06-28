'use client';
import { useState } from 'react';
import useSWR from 'swr';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Legend,
} from 'recharts';
import { fetcher } from '@/lib/api';
import { PROVIDERS, RATE_TYPES, AUTO_REFRESH_INTERVAL } from '@/lib/constants';
import { ChartLoadingSkeleton } from './LoadingState';
import { ErrorState } from './ErrorState';
import styles from './RateChart.module.css';

interface HistoryItem {
  rate_value: string;
  effective_date: string;
  ingestion_ts: string;
}

interface HistoryResponse {
  data: HistoryItem[];
  meta: { count: number; provider: string; rate_type: string };
}

// Custom tooltip component
function CustomTooltip({ active, payload, label }: {
  active?: boolean;
  payload?: Array<{ value: number }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className={styles.tooltip}>
      <p className={styles.tooltipDate}>{label}</p>
      <p className={styles.tooltipRate}>{Number(payload[0].value).toFixed(4)}%</p>
    </div>
  );
}

export default function RateChart() {
  const [provider, setProvider] = useState('Chase');
  const [rateType, setRateType] = useState('30yr_fixed_mortgage');

  // Fetch the 30 most recent records without date constraints
  const url = `/api/v1/rates/history/?provider=${encodeURIComponent(provider)}&type=${rateType}&page_size=30`;

  const { data, error, isLoading, mutate } = useSWR<HistoryResponse>(url, fetcher, {
    refreshInterval: AUTO_REFRESH_INTERVAL,
    dedupingInterval: 30_000,
  });

  // The backend returns newest first (descending), so we reverse it for the chart to go oldest -> newest
  const chartData = (data?.data || [])
    .map(d => ({
      date: d.effective_date,
      rate: parseFloat(d.rate_value),
    }))
    .reverse();

  return (
    <div className={styles.wrapper}>
      <div className={styles.controls}>
        <div className={styles.control}>
          <label htmlFor="chart-provider" className={styles.label}>Provider</label>
          <select
            id="chart-provider"
            value={provider}
            onChange={e => setProvider(e.target.value)}
            className={styles.select}
            aria-label="Select provider for chart"
          >
            {PROVIDERS.map(p => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </div>
        <div className={styles.control}>
          <label htmlFor="chart-rate-type" className={styles.label}>Rate Type</label>
          <select
            id="chart-rate-type"
            value={rateType}
            onChange={e => setRateType(e.target.value)}
            className={styles.select}
            aria-label="Select rate type for chart"
          >
            {RATE_TYPES.map(t => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
        </div>
      </div>

      {isLoading ? (
        <ChartLoadingSkeleton />
      ) : error ? (
        <ErrorState
          message={error.message}
          onRetry={() => mutate()}
          title="Failed to load history"
        />
      ) : chartData.length === 0 ? (
        <div className={styles.emptyChart}>
          <p>No data available for {provider} — {rateType} in the last 30 days.</p>
        </div>
      ) : (
        <div className={styles.chartContainer} id="rate-history-chart">
          <ResponsiveContainer width="100%" height={400}>
            <LineChart
              data={chartData}
              margin={{ top: 10, right: 20, left: 0, bottom: 10 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 11, fill: 'var(--text-muted)' }}
                tickLine={false}
                axisLine={{ stroke: 'var(--border)' }}
                interval="preserveStartEnd"
              />
              <YAxis
                domain={['auto', 'auto']}
                tick={{ fontSize: 11, fill: 'var(--text-muted)' }}
                tickLine={false}
                axisLine={false}
                tickFormatter={(v: number) => `${v.toFixed(2)}%`}
                width={60}
              />
              <Tooltip content={<CustomTooltip />} />
              <Line
                type="monotone"
                dataKey="rate"
                stroke="var(--accent)"
                strokeWidth={2.5}
                dot={false}
                activeDot={{ r: 5, fill: 'var(--accent)', stroke: 'var(--bg)' }}
                name={`${provider} ${rateType}`}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      <p className={styles.refreshNote}>
        Showing last 30 days · Auto-refreshes every 60 seconds
      </p>
    </div>
  );
}
