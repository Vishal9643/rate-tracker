'use client';
import styles from './LoadingState.module.css';

interface LoadingSkeletonProps {
  rows?: number;
}

export function LoadingSkeleton({ rows = 8 }: LoadingSkeletonProps) {
  return (
    <div className={styles.skeleton} role="status" aria-label="Loading...">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className={styles.skeletonRow}>
          <div className={styles.skeletonCell} style={{ width: '22%' }} />
          <div className={styles.skeletonCell} style={{ width: '28%' }} />
          <div className={styles.skeletonCell} style={{ width: '14%' }} />
          <div className={styles.skeletonCell} style={{ width: '18%' }} />
        </div>
      ))}
    </div>
  );
}

export function ChartLoadingSkeleton() {
  return (
    <div className={styles.chartSkeleton} role="status" aria-label="Loading chart...">
      <div className={styles.chartSkeletonInner} />
    </div>
  );
}
