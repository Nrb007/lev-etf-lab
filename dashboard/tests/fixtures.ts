import type { Detail, IndexData, JudgeValidation } from "../src/types";

const test = (value: number | null, threshold: number, pass: boolean, details = {}) => ({
  value,
  threshold,
  pass,
  details,
});

export const detailAdvance: Detail = {
  id: "H-0001",
  title: "Momentum",
  mechanism: "Trend persistence.",
  notes_on_prior_trials: "none",
  registered_at: "2026-09-30",
  universe: { fund: "TQQQ", underlying: "QQQ", research_universe: "real", leverage: 3 },
  param_names: ["window", "hurdle"],
  param_values: { window: [5, 10], hurdle: [0, 0.01] },
  chosen_params: { window: 10, hurdle: 0 },
  chosen_trial: "H-0001-000003",
  window: ["2010-02-12", "2024-05-29"],
  n_trials_hypothesis: 4,
  metrics: {
    strategy: { cagr: 0.4, sharpe: 2, max_drawdown: -0.2 },
    buy_and_hold: { cagr: 0.1, sharpe: 0.5, max_drawdown: -0.6 },
    half_cash: { cagr: 0.05, sharpe: 0.5, max_drawdown: -0.3 },
  },
  curves: [
    { date: "2010-02-12", equity_strategy: 1, equity_buy_and_hold: 1, equity_half_cash: 1, drawdown_strategy: 0, drawdown_buy_and_hold: 0, drawdown_half_cash: 0 },
    { date: "2011-02-12", equity_strategy: 1.4, equity_buy_and_hold: 1.1, equity_half_cash: 1.05, drawdown_strategy: -0.05, drawdown_buy_and_hold: -0.2, drawdown_half_cash: -0.1 },
  ],
  grid: [
    { params: { window: 5, hurdle: 0 }, sharpe: 1.5, trial: "t1" },
    { params: { window: 10, hurdle: 0 }, sharpe: 2, trial: "t3" },
    { params: { window: 5, hurdle: 0.01 }, sharpe: -0.5, trial: "t2" },
    { params: { window: 10, hurdle: 0.01 }, sharpe: null, trial: "t4" },
  ],
  verdict: {
    hypothesis_id: "H-0001",
    n_trials: 224,
    n_obs: 3597,
    seed: 1,
    thresholds_hash: "abcdef1234567890",
    tests: {
      dsr: test(0.99, 0.95, true),
      spa: test(0.004, 0.05, true),
      pbo: test(0, 0.3, true),
      permutation: test(0.001, 0.05, true),
      sensitivity: test(0.9, 0.6, true),
      stress: test(1.5, 0, true),
      regime: test(0.8, 0.6, true, {
        partitions: {
          year: { excess_by_regime: { "2010": 0.1, "2011": -0.05 }, fraction_positive: 0.5, max_share: 0.4, n_regimes: 2, total_excess: 0.05 },
          vix_tercile: { excess_by_regime: { "0": 0.2, "1": 0.1, "2": 0.3 }, fraction_positive: 1, max_share: null, n_regimes: 3, total_excess: 0.6 },
        },
      }),
    },
    train_verdict: "advance",
    reasons: [],
    holdout_verdict: null,
    chosen_params: { window: 10, hurdle: 0 },
    chosen_trial: "H-0001-000003",
  },
  reviews: { pre: "clear", post: "clear" },
  review_md: "Pre-run review\n\nRecommendation (pre-run): clear",
  report_md: "## Why it passed\n\nIt **held up** under `seven` tests.\n\n- one\n- two",
  holdout: null,
};

export const detailReject: Detail = {
  ...detailAdvance,
  id: "H-0002",
  title: "Noise",
  verdict: {
    ...detailAdvance.verdict,
    hypothesis_id: "H-0002",
    train_verdict: "reject",
    reasons: ["dsr", "regime"],
    tests: {
      ...detailAdvance.verdict.tests,
      dsr: test(0.2, 0.95, false),
      regime: test(0.3, 0.6, false, { partitions: {} }),
      pbo: test(null, 0.3, false, { reason: "insufficient trials" }),
    },
  },
  report_md: null,
  holdout: { verdict: "fail", scored_on: "2026-10-05" },
};

export const index: IndexData = {
  schema_version: 1,
  generated_at: "2026-09-30T12:00:00+00:00",
  n_trials: 224,
  funnel: { proposed: 2, passed_skeptic: 2, passed_judge: 1, passed_holdout: 0 },
  data_source: { source: "simulated-demo-world", simulated: true },
  expected_max_sharpe_annual: 3.21,
  thresholds_hash: ["abcdef1234567890"],
  hypotheses: [
    { id: "H-0001", title: "Momentum", train_verdict: "advance", reasons: [], holdout: null, skeptic_pre: "clear", skeptic_post: "clear", trials: 56, sharpe: 2, benchmark_sharpe: 0.5, cagr: 0.4, max_drawdown: -0.2 },
    { id: "H-0002", title: "Noise", train_verdict: "reject", reasons: ["dsr", "regime"], holdout: { verdict: "fail", scored_on: "2026-10-05" }, skeptic_pre: "clear", skeptic_post: "block", trials: 56, sharpe: 0.3, benchmark_sharpe: 0.5, cagr: 0.05, max_drawdown: -0.5 },
  ],
};

export const validation: JudgeValidation = {
  noise: { n: 200, t: 1500, advance_rate: 0, nominal: 0.05, tolerance: 0.046, rejections_by_test: { dsr: 197, spa: 188 } },
  planted_edge: [
    { beta: 0.2, edge_sharpe: 1.82, t: 1500, power: 0.27, runs: 30, rejections_by_test: { regime: 18 } },
    { beta: 0.2, edge_sharpe: 1.82, t: 3000, power: 0.5, runs: 30, rejections_by_test: { regime: 10 } },
    { beta: 0.3, edge_sharpe: 2.65, t: 1500, power: 0.4, runs: 30, rejections_by_test: {} },
    { beta: 0.3, edge_sharpe: 2.65, t: 3000, power: 0.87, runs: 30, rejections_by_test: { pbo: 2 } },
  ],
  snooping: { variants: 500, worlds: 8, advance_rate: 0, median_best_in_sample_sharpe: 1.1 },
};

export function mockFetch(routes: Record<string, unknown>) {
  globalThis.fetch = (async (url: string) => {
    const key = String(url).replace("./data/", "");
    if (!(key in routes)) return new Response("not found", { status: 404 });
    return new Response(JSON.stringify(routes[key]), { status: 200 });
  }) as typeof fetch;
}
