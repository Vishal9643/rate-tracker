import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';

const inter = Inter({ subsets: ['latin'], variable: '--font-inter' });

export const metadata: Metadata = {
  title: 'Rate Tracker — Live Interest Rate Dashboard',
  description:
    'Real-time mortgage and savings rate comparison across major US financial providers. Updated automatically every 60 seconds.',
  keywords: 'mortgage rates, savings rates, interest rates, rate comparison, financial data',
  openGraph: {
    title: 'Rate Tracker',
    description: 'Live interest rate dashboard for major US financial providers',
    type: 'website',
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={inter.variable}>
      <body>{children}</body>
    </html>
  );
}
