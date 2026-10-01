// Shapes of the JSON written by core/dashboard_export.py and the judge (results/).

export type TrainVerdict = "advance" | "reject";
export type HoldoutOutcome = "pass" | "fail" | "error";

export interface HoldoutStatus {
  verdict: HoldoutOutcome;
  scored_on: string;
}

export interface IndexRow {
  id: string;
  title: string;
  train_verdict: TrainVerdict;
  reasons: string[];
  holdout: HoldoutStatus | null;
  skeptic_pre: "clear" | "block" | null;
  skeptic_post: "clear" | "block" | null;
  trials: number;
  sharpe: number | null;
  benchmark_sharpe: number | null;
  cagr: number | null;
  max_drawdown: number | null;
}

export interface IndexData {
  schema_version: number;
  generated_at: string;
  n_trials: number;
  funnel: Record<"proposed" | "passed_skeptic" | "passed_judge" | "passed_holdout", number>;
  data_source: { source: string; simulated: boolean } | null;
  expected_max_sharpe_annual: number | null;
  thresholds_hash: string[];
  hypotheses: IndexRow[];
}

export interface TestResult {
  value: number | null;
  threshold: number;
  pass: boolean;
  details: Record<string, unknown>;
}

export interface RegimePartition {
  excess_by_regime: Record<string, number>;
  fraction_positive: number | null;
  max_share: number | null;
  n_regimes: number;
  total_excess: number;
}

export interface Verdict {
  hypothesis_id: string;
  n_trials: number;
  n_obs: number;
  seed: number;
  thresholds_hash: string;
  tests: Record<string, TestResult>;
  train_verdict: TrainVerdict;
  reasons: string[];
  holdout_verdict: string | null;
  chosen_params: Record<string, number | string>;
  chosen_trial: string;
}

export interface CurveRow {
  date: string;
  [key: string]: number | string;
}

export type Metrics = Record<string, number | null>;

export interface Detail {
  id: string;
  title: string;
  mechanism: string;
  notes_on_prior_trials: string;
  registered_at: string;
  universe: { fund: string; underlying: string | null; research_universe: string; leverage: number };
  param_names: string[];
  param_values: Record<string, (number | string)[]>;
  chosen_params: Record<string, number | string>;
  chosen_trial: string;
  window: [string, string];
  n_trials_hypothesis: number;
  metrics: { strategy: Metrics; buy_and_hold: Metrics; half_cash: Metrics };
  curves: CurveRow[];
  grid: { params: Record<string, number | string>; sharpe: number | null; trial: string }[];
  verdict: Verdict;
  reviews: { pre: string | null; post: string | null };
  review_md: string | null;
  report_md: string | null;
  holdout: HoldoutStatus | null;
}

export interface JudgeValidation {
  noise: {
    n: number;
    t: number;
    advance_rate: number;
    nominal: number;
    tolerance: number;
    rejections_by_test: Record<string, number>;
  };
  planted_edge: {
    beta: number;
    edge_sharpe: number;
    t: number;
    power: number;
    runs: number;
    rejections_by_test: Record<string, number>;
  }[];
  snooping: { variants: number; worlds: number; advance_rate: number; median_best_in_sample_sharpe: number };
  source?: Record<string, unknown>;
}
