# H-0002: Hold while implied volatility is calm (demo)

**Judge result (train split): `reject`.** N = 224 trials counted.

> **This is a demo on a simulated universe.** It was built by `scripts/build_demo_world.py`, not from market data. The spec says that in this simulated world the VIX is independent of returns, so the mechanism has nothing to find and the hypothesis "is expected to fail". None of these numbers is evidence about real TQQQ. The spec and the ledger rows still carry `research_universe: real`. The skeptic flagged that label as inconsistent and misleading, and it should be ignored for this demo.

Sources: `hypotheses/H-0002_vix_calm.yaml` (spec), `results/H-0002/verdict.json`, `results/H-0002/review.md`, `ledger/trials.jsonl`.

## What was tested

- **Idea (spec):** volatility drag on a daily-reset 3x fund grows with realized variance, and variance clusters. So hold the fund while a smoothed VIX is below a level, and sit in cash otherwise.
- **Fund / underlying:** TQQQ / QQQ. **Benchmark:** buy-and-hold. **Primary metric:** Sharpe.
- **Grid (spec):** `window` in {1, 2, 3, 5, 8, 13, 21, 34} × `vix_max` in {16, 18, 20, 22, 24, 26, 28}. That is 56 parameter combinations, and the ledger holds 56 H-0002 trials.
- **Chosen by the judge:** `vix_max` = 22, `window` = 34 (trial `H-0002-000109`).
- **Observations:** `n_obs` = 3597. Trial window 2010-02-12 to 2024-05-29, split `train`. Seed 20260929.
- **Ledger metrics for the chosen trial (`trials.jsonl`, n=109):** Sharpe 1.3696, CAGR 0.8152, max drawdown -0.9974, time in market 0.7645, total turnover 35.0, total cost 0.0175 at cost_bps 5.0.

## Why N = 224 matters

`n_trials` is 224 in `verdict.json`. The skeptic notes that this counts every trial in the ledger, not only H-0002's 56. Each extra trial is another chance to find a good-looking result by luck. The judge therefore asks the best result to clear a bar that rises with N. With 224 tries, a strategy has to beat what the best of 224 random tries would typically show. This is the main reason the deflated Sharpe test is so hard to pass.

## Failing tests (`reasons`: "dsr", "permutation", "sensitivity", "regime")

| Test | Value | Threshold | Result |
|---|---|---|---|
| `dsr` | 4.476770823152431e-21 | 0.95 | fail |
| `permutation` | 0.2046149569085349 | 0.05 | fail |
| `sensitivity` | 0.8928359052705263 | 0.6 | fail |
| `regime` | 0.4666666666666667 | 0.6 | fail |

**`dsr` (deflated Sharpe ratio).** This estimates the probability that the strategy's Sharpe is real after correcting for how many trials were run, plus skew and kurtosis. The judge requires at least 0.95, and the value is effectively zero. The details show a per-period Sharpe of 0.0863 against an expected maximum Sharpe of 0.2417 from 224 trials. The observed Sharpe is well below what selection from 224 trials would produce by chance.

**`permutation`.** This shifts the signal in time to build a "no real timing skill" distribution, then asks how often chance does as well as the observed result. The p-value is 0.205, and it needs to be at most 0.05. The observed Sharpe of 1.3696 is below the null 95th percentile of 1.6663. The null mean Sharpe is already 1.0647, so most of the Sharpe appears without the timing signal. The details report full enumeration with 3596 shifts.

**`sensitivity`.** This checks whether nearby parameter settings still work, so the result is not a lucky spike. The chosen Sharpe is 1.3696 against a buy-and-hold benchmark Sharpe of 1.2217. `fraction_beating_benchmark` is 0.625 against a listed threshold of 0.8, across 8 neighbours. Some neighbours were weak. At `vix_max` 13 the Sharpe is 0.1236, and at `vix_max` 18 it is 0.8760. The `value` field shows 0.8928 against a 0.6 threshold yet is marked as a fail. The skeptic also flagged that this field's meaning is unclear. I report it as returned and do not reinterpret it.

**`regime`.** This checks whether the edge over the benchmark shows up across different market regimes or comes from a few. The fraction of positive regimes is 0.4667 against a 0.6 threshold. The details show:
- Year partition: 15 years, fraction positive 0.4667. Total excess is -0.4005. The worst years are 2015 (-1.9846) and 2016 (-0.9852).
- VIX-tercile partition: excess of 0.2941, 0.8065 and -1.5011 for terciles 0, 1 and 2. Fraction positive is 0.6667.
- `max_single_regime_share` is null, so that concentration check produced no value.

## Tests that passed

`pbo` (0.0 against a 0.3 threshold), `spa` (0.02 against 0.05) and `stress` (0.1506 against 0.0, under 3x costs and 200 bps financing spread) passed. The skeptic advises against reading the `pbo` and `spa` passes as support for the strategy. It calls a PBO of exactly 0.0 unusually clean and says SPA passed only narrowly. It says both conflict with the DSR and permutation failures and are likely artefacts of comparing against a weak set of models. The verdict is still `reject`.

## Skeptic's review (`review.md`)

- **Pre-run recommendation: `clear`.** Findings:
  - The leakage check reported no leakage across 56 grid points.
  - The 56-point grid is large and unjustified by the spec.
  - The `research_universe: real` label conflicts with the spec notes.
  - No cost or turnover expectation was stated.
  - The skeptic did not confirm the engine's execution lag, `holdout_start` or near-duplicate specs.
- **Post-run recommendation: `block`.** Findings:
  - The reject is consistent with the test values, and the skeptic sees nothing arguing for an override.
  - The maximum drawdown of -99.7% means the strategy was nearly wiped out.
  - The chosen `window` of 34 sits on the top edge of the grid, so larger windows were never tried. This may be a boundary artefact.
  - The stress-test margin is small.
  - Turnover is low and cost is not driving the result.
  - The skeptic did not recompute any numbers.

## Caveats

- **One long bull market, small effective sample.** The data span one long rising stretch (2010 to 2024 here). Many observations are not independent, so the effective sample is much smaller than `n_obs` = 3597 suggests.
- **Train split only.** Everything above is on the train split. The hold-out is scored once, by a human-run command, and only after human approval. `holdout_verdict` in `verdict.json` is null, so **the hold-out has not been scored**, and this report states nothing about it.
- **A rejection is a valid result.** It is what the spec predicted for this simulated universe.
- **Simulated data.** See the note at the top.
- **Not investment advice.**
