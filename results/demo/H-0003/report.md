# H-0003 report: Calendar-window holding (demo)

Sources: `hypotheses/H-0003_turn_of_month.yaml` (spec), `results/H-0003/verdict.json` (verdict), `results/H-0003/review.md` (skeptic), `ledger/trials.jsonl` (trials).

**This is a demo on a simulated universe** (built by `scripts/build_demo_world.py`). It does not use real market data. Nothing below says anything about real markets.

## Verdict

- **train_verdict: `reject`** (verdict.json)
- **N (n_trials): 224**, with n_obs 3597 (verdict.json)
- **reasons** (verbatim): `dsr`, `permutation`, `sensitivity`, `stress`, `regime`
- holdout_verdict: null. **The hold-out has not been scored.**
- Chosen trial: H-0003-000119, params length 24 and start_day 1 (verdict.json)

## What was tested

The spec holds TQQQ only while the calendar day of the month is inside a window, and sits in cash otherwise. The grid is 8 start_day values x 7 length values. The spec's stated mechanism is month-boundary flow seasonality. The spec also says that in the simulated universe returns have no calendar structure, so this is "a pure-noise hypothesis expected to fail". The benchmark is buy_and_hold and the primary metric is Sharpe.

## Failing tests

| Test | Value | Threshold | Plain meaning |
|---|---|---|---|
| dsr | 6.776858593325345e-25 | 0.95 | The Deflated Sharpe Ratio is the probability that the Sharpe ratio is real after accounting for how many strategies were tried. Here the per-period Sharpe is 0.0713 and the expected best Sharpe from pure luck across the trials is 0.2417 (details). The observed Sharpe is well below what luck alone would produce. |
| permutation | 0.23519599666388658 | 0.05 | The window is shifted to other positions and the Sharpe is recomputed. The p-value is the share of shifts that do as well. The observed Sharpe is 1.1322, the null mean is 1.0648 and the null 95th percentile is 1.2123. A randomly placed window does about as well, so the result does not show timing skill. |
| sensitivity | value 0.9328886818188684 against threshold 0.6; fraction_beating_benchmark 0.0 against 0.8 | see left | Nearby parameters are checked to see if the result holds up. The strategy's base Sharpe is 1.1322 and the benchmark Sharpe is 1.2217. None of the 4 neighbours beat the benchmark (fraction 0.0 against the 0.8 threshold). The `value` field alone, read against 0.6, looks like a pass. The skeptic notes that the pass rule uses `fraction_beating_benchmark`. |
| stress | -0.12575789722739183 | 0.0 | The strategy is re-run with 3.0x costs and a 200 bps financing spread. The result is below zero, so it does not survive harsher costs. |
| regime | 0.0 | 0.6 | The result is split by VIX tercile and by year. Total excess is -1.8344 in both splits. 0 of 3 VIX terciles are positive, and 7 of 15 years are positive (fraction_positive 0.4667). `max_single_regime_share` is null, so concentration was not measured (details). |

## Tests that passed

- **pbo**: 0.0 against a threshold of 0.3 (pass).
- **spa**: 0.02 against a threshold of 0.05 (pass).

The skeptic says neither pass should be used as support. Its reasoning is that PBO is uninformative when all trials are nearly the same long-biased exposure. It also thinks SPA is probably picking up the simulated universe's positive drift and not calendar skill. These are the skeptic's readings, not judge outputs. The verdict is still `reject`.

## Why N makes passing harder

N is the number of trials counted in the ledger, here 224. The more variants are tried, the better the best one looks by chance alone. The DSR test deflates the best Sharpe by the Sharpe that luck would produce across N tries. That expected maximum is 0.2417 per period, against an observed 0.0713. The SPA test and the PBO test also use all 224 models. A strategy that looks good in one trial must beat what the best of hundreds of tries would show anyway.

The spec's grid has 56 points, but n_trials is 224. The skeptic flagged this gap and asked that its source be confirmed. A search of the ledger for "H-0003" matched 56 lines (lines 113 to 168). I did not open the long rows, so I cannot say where 224 comes from.

## Skeptic review (review.md)

- **Pre-run recommendation: `clear`.** Findings included:
  - No leakage was found across 56 grid points.
  - The grid has no stated justification and the mechanism does not match it: start days of 8 to 24 with short lengths are mid-month windows, not a turn of month.
  - Windows do not wrap past month end, so many grid points are near-duplicates.
  - `research_universe: real` in the spec contradicts the demo notes, and the skeptic asked for confirmation that `lab run` uses the simulated world.
  - The skeptic could not check `holdout_start` or duplicates against H-0001 and H-0002.
- **Post-run recommendation: `block`.** Findings included:
  - The verdict matches the metrics.
  - The best Sharpe rises with length (14: 0.75, 19: 0.96, 24: 1.13, 29: 1.15, 34: 1.22), a drift toward holding almost all month. The skeptic calls this buy-and-hold in disguise, not a calendar effect. The chosen length of 24 is the top of the spec's length values.
  - The strategy is below buy-and-hold (1.1322 against 1.2217).
  - The skeptic could not check the H-0003 trials individually (time in market, turnover, cost). Its findings rest on verdict.json.
  - The skeptic noted the `value` versus `threshold` display confusion in the sensitivity entry.

## Caveats

- The data is one simulated, long bull-market-style history, with a small effective sample (3597 observations, but only 15 calendar years and heavily overlapping parameter variants). Results depend strongly on that one path.
- These results are on the **train split only**.
- A rejection is a valid result. The spec itself predicted it.
- The skeptic could not verify some items (see above), so they remain unchecked.
- None of this is investment advice.

## Hold-out

The hold-out has not been scored (`holdout_verdict` is null in verdict.json). It is scored once, by a human-run command, and only after human approval. This report makes no statement about a hold-out result.
