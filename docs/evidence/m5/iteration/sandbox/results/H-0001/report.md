# H-0001 report: Volatility-targeted exposure to limit leveraged vol drag

Sources: `hypotheses/H-0001_voltarget_drag.yaml` (spec), `results/H-0001/verdict.json` (verdict), `results/H-0001/review.md` (skeptic), `ledger/trials.jsonl` (trials).

## Outcome

- **train_verdict: `reject`** (verdict.json).
- **N (n_trials) = 9**, with n_obs = 3597 (verdict.json).
- **reasons** (verbatim from verdict.json): `["spa", "pbo", "regime"]`.
- **holdout_verdict: null.** The hold-out has not been scored.

A rejection is a valid result. It is not a bug and it is not something to work around.

## What was tested

The spec says a daily-reset leveraged fund loses growth to volatility drag. That drag grows with the square of realized volatility. Trailing volatility is a usable forecast of near-term volatility. So the strategy scales exposure by `target_vol / trailing_vol`, capped at 1, with the remainder in cash. The fund is TQQQ and the underlying is QQQ. The benchmark is buy-and-hold and the primary metric is Sharpe. The spec says the mechanism predicts a lower-volatility, smaller-drawdown path and "does not assume higher raw return".

The grid was lookback in {10, 20, 60} times target_vol in {0.4, 0.6, 0.8}. That is 9 points, and each counts toward N. The judge chose trial `H-0001-000002` with `lookback` 10 and `target_vol` 0.6.

## Failing tests

| Test | Value | Threshold | Result |
|---|---|---|---|
| `spa` | 0.958 | 0.05 | fail |
| `pbo` | null (status `insufficient_trials`) | 0.3 | fail |
| `regime` | 0.0 | 0.6 | fail |

### What each one means

- **`spa` (Superior Predictive Ability).** This asks whether the best of the 9 tried variants really beats the benchmark once you allow for having picked the best of several. A small p-value would say yes. The value here is 0.958 against a 0.05 threshold. The details show `p_lower` 0.577 and `p_upper` 0.96, with 9 models, a block size of 60 and 1000 reps. In plain terms, the winner cannot be told apart from luck-of-the-draw selection.
- **`pbo` (probability of backtest overfitting).** This estimates how often the variant that looks best in-sample does badly out of sample. It needs at least 50 comparable trials (`min_trials`: 50). This run had 9 (`n_comparable_trials`: 9). The judge therefore returned no value (`reason`: "insufficient trials") and counted it as a fail. The skeptic notes this is a structural limit of a 9-point grid. It is not evidence for or against the idea. Overfitting of the selection is untested.
- **`regime`.** This asks whether the result holds across market conditions, or whether one period carries it. The value is 0.0 against a 0.6 threshold. `fraction_positive` is 0.0 across the three VIX terciles (excess -0.0539, -0.5303, -0.1126; total -0.6968). Across the 15 calendar years it is 0.1333, meaning only 2 years were positive: 2018 (+0.0464) and 2022 (+0.1978). The worst years were 2020 (-0.2430) and 2011 (-0.1646). `max_single_regime_share` is null in the verdict, and the skeptic says this is because total excess is negative.

### Why N makes passing harder

Every variant tried is another chance to find a good-looking result by luck. The tests therefore judge the best result against what the best of N random tries would produce, and the bar rises as N grows. Here N = 9. The `dsr` deflation is described by the skeptic as mild at this N. `spa` and `pbo` are exactly the tests that account for selection among trials. A small grid also cannot supply the 50 trials `pbo` needs.

## Tests that passed

- `dsr`: value 0.9996139407175451 against a threshold of 0.95, pass.
- `permutation`: value 0.015012510425354461 against a threshold of 0.05, pass. The observed Sharpe was 0.9803, against a null mean of 0.8562 and a null p95 of 0.9288.
- `sensitivity`: value 0.9986376975094747 against a threshold of 0.6, pass. `fraction_beating_benchmark` was 1.0. The benchmark Sharpe was 0.8719 and the base Sharpe was 0.9803.
- `stress` (3x costs, 200 bps financing spread): value 0.0914 against a threshold of 0.0, pass.

The judge's verdict is `reject` even though these pass. The skeptic advises giving the `spa` and `regime` results more weight than `dsr`, and calls the `sensitivity` pass weak evidence (see below).

## Skeptic's review (review.md)

- **Pre-run: `clear`.** No lookahead was found in the signal. The skeptic cited the `lab leakage` output, "no leakage across 9 grid points", and said the conclusion rests on that output. It flagged that the grid is partly degenerate. Because the position is capped at 1.0, target_vol 0.8 is close to buy-and-hold. This may inflate N without adding independent tests. It also noted that a Sharpe gain could come from generic de-risking or the cash leg, not from drag avoidance. The judge's benchmark is buy-and-hold only, so any outperformance cannot be attributed to vol drag specifically.
- **Post-run: `block`.** The skeptic recommended `block`. The main findings:
  - The verdict matches the test fields, and the hypothesis should not advance to hold-out consideration.
  - The strategy trails the benchmark in nearly every regime. The only positive years are the 2018 and 2022 drawdown years, which the skeptic reads as what de-risking does, not as evidence of drag avoidance.
  - Every sensitivity neighbour beats the benchmark Sharpe, but only by about 0.05 to 0.14. Sharpe is nearly flat across target_vol, so the parameter looks mostly inert. The lookback = 20 and 60 side, where Sharpe is lower, is not tested.
  - The chosen point is at the lower edge of the lookback grid, and its lookback-12 neighbour scores higher (1.0147), so the optimum is not bracketed. Trial 000002 (Sharpe 0.9803 in the ledger's trial row is 0.9802583) beats trial 000001 (0.9773) by about 0.003, which the skeptic calls noise.
  - The mechanism promised lower volatility and smaller drawdowns. The chosen trial has `max_drawdown` -0.7159 and `ann_vol` 0.4891 (ledger). Trial 000001 (target_vol 0.4) has `max_drawdown` -0.5503 and `ann_vol` 0.3980. The judge selected on Sharpe, so the mechanism claim itself was not what was tested.
  - `time_in_market` is 0.9972 for the chosen trial, so the strategy is essentially always invested. The `stress` value of 0.0914 only barely clears zero, so the skeptic calls it fragile to worse financing.
  - No hold-out contamination is visible.

## Caveats

- **One long bull market, small effective sample.** The train window runs 2010-02-12 to 2024-05-29 (ledger). It is mostly one long equity bull market, so the number of independent market conditions is small, even though n_obs is 3597 daily observations.
- **Train split only.** Every number here comes from the train split. Nothing has been measured out of sample.
- **Hold-out.** The hold-out is scored once, by a human-run command, and only after human approval. `holdout_verdict` is null, so it has not been scored. This report makes no statement about any hold-out result.
- **A rejection is a valid result.** It says this idea, tested this way, did not clear the judge's bar.
- **Not investment advice.** This is a research report on a backtest and nothing more.
