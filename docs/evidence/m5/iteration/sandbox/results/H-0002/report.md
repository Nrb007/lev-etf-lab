# H-0002 report: Trend and implied-vol regime filter for holding TQQQ

Sources: `hypotheses/H-0002_trend_vix_regime.yaml` (spec), `results/H-0002/verdict.json` (verdict), `results/H-0002/review.md` (skeptic), `ledger/trials.jsonl` (trials). Every number below comes from one of these, and the file is named.

## Result

**`train_verdict`: reject** (verdict.json). N = `n_trials` = **18**, over `n_obs` = 3597 daily observations. The `holdout_verdict` is null, so the hold-out has not been scored.

A rejection is a valid result. It tells us this idea did not survive the lab's tests on the train split.

## What was tested

The spec proposes holding TQQQ (the 3x leveraged fund, with QQQ as the underlying) only when QQQ is above its trailing mean and VIX is not spiking above its own trailing average. The reasoning is that daily-reset leverage drags on returns when volatility is high and trends reverse, and holds up better in calm uptrends. The benchmark is buy-and-hold. The primary metric is Sharpe. The grid is `trend_window` in {50, 100, 200} and `vix_ratio` in {1.1, 1.25, 1.5}.

The chosen trial was `H-0002-000018` with `trend_window` 200 and `vix_ratio` 1.5.

## Failing tests (verdict.json `reasons`, verbatim)

`"spa"`, `"pbo"`, `"permutation"`, `"sensitivity"`, `"stress"`, `"regime"`

Six tests fail. Only `dsr` passes.

| Test | Value | Threshold | Meaning |
|---|---|---|---|
| spa | 0.958 | 0.05 | Tests whether the best strategy beats the benchmark by more than luck, given all the variants tried. This is a p-value, and it should be below 0.05. Here it is far above. |
| pbo | null (`insufficient_trials`) | 0.3 | Estimates the probability that the "best" pick is an overfit. It needs at least 50 trials (`min_trials`) and only 18 were comparable. It could not be computed and counts as a fail. |
| permutation | 0.1993 | 0.05 | Compares the observed Sharpe (0.851) with Sharpe under shuffled timing. The null 95th percentile is 0.943 and the null mean is 0.763. The observed Sharpe does not stand out from the shuffled results. |
| sensitivity | 0.9956 (`value`, as returned) | 0.6 | Tests whether nearby parameter settings also do well. `details.fraction_beating_benchmark` is 0.125 against `fraction_beating_benchmark_threshold` 0.8, with 8 neighbours. Only 1 of 8 beat the benchmark's Sharpe of 0.872. The `value` field and the fraction field disagree; the `pass` flag is false. |
| stress | -0.0465 | 0.0 | Sharpe with costs tripled (`cost_multiplier` 3.0) and a 200 bps financing spread. It should stay above 0. It goes negative. |
| regime | 0.0667 | 0.6 | The fraction of regimes where the strategy beat the benchmark. It was positive in 1 of 15 calendar years (only 2022, +0.58). In the VIX-tercile split it was positive in 1 of 3 (0.333). Total excess return versus the benchmark is -2.44. |

`dsr` passed (0.991 against 0.95). The skeptic warns that this only shows the absolute Sharpe (0.851) beats the expected best of 18 noise trials. It is not a test against buy-and-hold, whose Sharpe (0.872, `tests.sensitivity.details.benchmark_sharpe`) is higher. The DSR pass should not be cited as support.

## Why N makes passing harder

N = 18 counts every variant tried (the skeptic says this includes the 9 H-0001 trials as well as the 9 H-0002 trials, and asks the human to confirm that this is the intended global count). When you try many variants and report the best, some look good by chance. The tests therefore raise the bar as N grows. The DSR compares the result to the expected best Sharpe of N pure-noise trials (0.0134 per period in `dsr.details`). SPA judges the best model against all N models together. PBO needs a large pool (50 or more) to say anything, and 18 is too few. More trials mean a higher bar and less room for a lucky pick.

## Skeptic's review (review.md)

- **Pre-run recommendation: clear.** No leakage was found across 9 grid points. The skeptic flagged the silent VIX fallback, `trend_window` doing two jobs, and a contradictory note about prior trials (N = 0 versus "related to H-0001"). The post-run review says the VIX fallback did not bite, because results changed across `vix_ratio`.
- **Post-run recommendation: block.** The skeptic states that nothing supports advancing this hypothesis. Its findings:
  - No edge over buy-and-hold on the train split, and the result depends on one year (2022).
  - The chosen point sits at the corner of the grid (maximum of both parameters), and Sharpe rises with both. The skeptic reads this as the filter weakening toward buy-and-hold, and not as a working regime filter.
  - Turnover is high for a binary filter (109 at the chosen point, 327 at trend_window 50 / vix_ratio 1.1), which points to whipsaw around the VIX threshold.
  - The `sensitivity` `value` field does not match `fraction_beating_benchmark`. The skeptic suggests someone check `core/judge`. The verdict is unaffected because `pass` is false.
  - PBO could not be computed, so overfitting is not ruled out.

## Caveats

- The data is one long bull market with a small effective sample. Fifteen calendar years is not much independent evidence about regimes.
- These results are on the **train split only**.
- A rejection is a valid result and is reported here as returned.
- None of this is investment advice.

## Hold-out

The hold-out is scored once, by a human-run command, and only after human approval. `holdout_verdict` in verdict.json is null: **the hold-out has not been scored.** This report makes no statement about it.
