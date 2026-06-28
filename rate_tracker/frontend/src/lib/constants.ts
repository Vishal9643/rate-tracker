// src/lib/constants.ts

export const PROVIDERS = [
  'Bank of America',
  'Capital One',
  'Chase',
  'Citibank',
  'HSBC',
  'PNC Bank',
  'TD Bank',
  'Truist',
  'US Bancorp',
  'Wells Fargo',
];

export const RATE_TYPES = [
  { value: '30yr_fixed_mortgage', label: '30yr Fixed Mortgage' },
  { value: '15yr_fixed_mortgage', label: '15yr Fixed Mortgage' },
  { value: '5yr_arm_mortgage', label: '5yr ARM Mortgage' },
  { value: 'savings_1yr_fixed', label: 'Savings 1yr Fixed' },
  { value: 'savings_easy_access', label: 'Savings Easy Access' },
];

export const RATE_TYPE_LABELS: Record<string, string> = Object.fromEntries(
  RATE_TYPES.map((t) => [t.value, t.label])
);

export const AUTO_REFRESH_INTERVAL = 60_000; // 60 seconds
