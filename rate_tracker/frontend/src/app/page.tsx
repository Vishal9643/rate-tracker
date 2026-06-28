import RateTable from '@/components/RateTable';
import RateChart from '@/components/RateChart';
import styles from './page.module.css';

export default function DashboardPage() {
  return (
    <main className={styles.main}>
      {/* Header */}
      <header className={styles.header}>
        <div className={styles.headerContent}>
          <div className={styles.logo}>
            <span className={styles.logoIcon}>📈</span>
            <span className={styles.logoText}>Rate Tracker</span>
          </div>
          <p className={styles.subtitle}>
            Live interest rates from major US financial providers
          </p>
        </div>
      </header>

      {/* Dashboard Content */}
      <div className={styles.dashboard}>
        {/* Rate Comparison Table Section */}
        <section className={styles.section} aria-labelledby="rates-table-heading">
          <div className={styles.sectionHeader}>
            <h2 id="rates-table-heading" className={styles.sectionTitle}>
              Latest Rates
            </h2>
            <p className={styles.sectionDesc}>
              Most recent rate per provider, sorted and filterable
            </p>
          </div>
          <RateTable />
        </section>

        {/* Rate History Chart Section */}
        <section className={styles.section} aria-labelledby="rate-chart-heading">
          <div className={styles.sectionHeader}>
            <h2 id="rate-chart-heading" className={styles.sectionTitle}>
              30-Day History
            </h2>
            <p className={styles.sectionDesc}>
              Rate trend for a selected provider and type
            </p>
          </div>
          <RateChart />
        </section>
      </div>

      <footer className={styles.footer}>
        <p>Rate Tracker · Data refreshed automatically every 60 seconds</p>
      </footer>
    </main>
  );
}
