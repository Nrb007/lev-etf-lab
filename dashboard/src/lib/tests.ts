// Display metadata for the judge's test battery (SPEC Section 6.1). The thresholds themselves come
// from the verdict JSON (config/thresholds.yaml), never from here.

export interface TestMeta {
  key: string;
  label: string;
  /** how the value is compared with the threshold */
  op: ">=" | "<=" | ">";
  short: string;
}

export const TEST_ORDER: TestMeta[] = [
  { key: "dsr", label: "Deflated Sharpe ratio", op: ">=", short: "Probability the Sharpe beats what N trials of noise would produce" },
  { key: "spa", label: "SPA / reality check", op: "<=", short: "p-value against buy-and-hold, with every trial as the model set" },
  { key: "pbo", label: "Probability of backtest overfitting", op: "<=", short: "CSCV: how often the in-sample winner ranks below median out of sample" },
  { key: "permutation", label: "Circular-shift permutation", op: "<=", short: "p-value of the Sharpe against time-shifted signals" },
  { key: "sensitivity", label: "Parameter sensitivity", op: ">=", short: "Median neighbour Sharpe as a fraction of the chosen point's" },
  { key: "stress", label: "Cost and financing stress", op: ">", short: "Excess Sharpe with costs x3 and financing +200 bps" },
  { key: "regime", label: "Regime stability", op: ">=", short: "Fraction of regimes (years, VIX terciles) with positive excess" },
];

export const TEST_LABEL: Record<string, string> = Object.fromEntries(TEST_ORDER.map((t) => [t.key, t.label]));

export function testLabel(key: string): string {
  return TEST_LABEL[key] ?? key;
}
