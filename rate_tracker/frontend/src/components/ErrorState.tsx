'use client';
import styles from './ErrorState.module.css';

interface ErrorStateProps {
  message: string;
  onRetry?: () => void;
  title?: string;
}

export function ErrorState({ message, onRetry, title = 'Something went wrong' }: ErrorStateProps) {
  return (
    <div className={styles.errorContainer} role="alert">
      <div className={styles.errorIcon}>⚠️</div>
      <h3 className={styles.errorTitle}>{title}</h3>
      <p className={styles.errorMessage}>{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className={styles.retryButton}
          id="retry-btn"
          aria-label="Retry data fetch"
        >
          <span>↺</span> Try Again
        </button>
      )}
    </div>
  );
}
