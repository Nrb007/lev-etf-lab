# H-0004 report: "Buy the fear - hold when implied volatility is high (demo)"

**Judge result (`results/H-0004/verdict.json`): `train_verdict` = `reject`. N = 224 trials (`n_trials`).**
The hold-out has not been scored (`holdout_verdict` is null).

> **Demo data.** This run uses a simulated universe built by `scripts/build_demo_world.py`, not real market data. Nothing here is evidence about real markets. The spec (`hypotheses/H-0004_fear_buyer.yaml`) says the VIX is independent of returns in this universe and that the hypothesis "is expected to fail".

## What was tested

From the spec: hold the fund (TQQQ, underlying QQQ) only while a smoothed VIX is above a level. The grid is `window` in {1, 2, 3, 5, 8, 13, 21, 34} and `vix_min` in {16, 18, 20, 22, 24, 26, 28}, which is 56 points. The benchmark is buy-and-hold and the primary metric is Sharpe. The spec is the mirror image of H-0002's VIX feature ("the opposite sign").

The judge picked trial `H-0004-000211` (`chosen_params`: `vix_min` 16, `window` 21) on `n_obs` = 3597. In `sensitivity`, the chosen point's Sharpe (`base_sharpe`) is 1.1452800435133674. Buy-and-hold's (`benchmark_sharpe`) is 1.2217177075266203.

## The verdict, verbatim

`reasons`: `"dsr"`, `"permutation"`, `"sensitivity"`, `"stress"`, `"regime"`.

## Failing tests (value vs threshold, all from `verdict.json`)

| Test | Value | Threshold | Plain meaning |
|---|---|---|---|
| `dsr` | 1.0315418619772112e-24 | 0.95 | Deflated Sharpe ratio. It asks how likely the Sharpe is real once you account for picking the best of N tries. Details: per-period Sharpe 0.0721458613490858 vs an expected best-of-N Sharpe of 0.24172312134268095 from pure luck. The winner is far below what luck alone would produce among 224 tries. |
| `permutation` | 0.3363914373088685 | 0.05 (p-value) | Compares the observed Sharpe (1.1452800435133674) to time-shifted copies of the signal. The null mean is 1.0218744880963027 and the null 95th percentile is 1.7965350115283985. About a third of shifted versions do as well, so the timing carries no detectable information. |
| `sensitivity` | 0.9764989115739532 | 0.6 | Looks at nearby parameter settings (8 neighbours). Per the details, `fraction_beating_benchmark` is 0.0 against a threshold of 0.8, so no neighbour beat buy-and-hold. The headline `value` field is easy to misread as a pass, but `pass` is false. |
| `stress` | -0.07250486893009267 | 0.0 | Re-runs with 3.0x costs and a 200 bps financing spread. The result is below zero, so the strategy does not survive harsher costs. |
| `regime` | 0.0 | 0.6 | Checks whether the edge holds across market conditions. Total excess return over the benchmark is negative (-2.1692822645809855) in both partitions. In the `vix_tercile` partition, `fraction_positive` is 0.0 (all three terciles negative). By year, `fraction_positive` is 0.5333333333333333 (8 of 15 years positive). |

Passing tests: `pbo` (value 0.0 vs threshold 0.3) and `spa` (value 0.02 vs threshold 0.05). The skeptic warns against reading these as positive evidence (see below). This report does not reinterpret the verdict, which is `reject`.

## Why N makes passing harder

N is the number of trials counted. Try many variants and the best one will look good partly by luck. The judge corrects for this. The more trials counted, the higher the Sharpe a pure-noise search is expected to find, and the chosen result has to beat that bar. Here N = 224 and the expected best-of-N Sharpe per period is 0.2417, about three times the chosen point's 0.0721. The `dsr` test fails by a wide margin.

On the count: `verdict.json` says `n_trials` is 224, but the spec grid has 56 points. The ledger file `ledger/trials.jsonl` has 224 lines in total. The lines that match "H-0004" are lines 169 to 224, which is 56 lines. I did not check the ledger's internal details beyond this. The post-run review flagged the gap and asked for an explanation. I can't settle it from these files.

## Skeptic's findings (`results/H-0004/review.md`)

- **Pre-run recommendation: `clear`.**
  - No lookahead was found, and `lab leakage H-0004` reported none across 56 grid points.
  - The grid is large for a thin idea, and the mechanism is circular. Both points were noted as acceptable for a demo only.
  - The spec is a sign flip of H-0002, which is a cheap way to add trials.
  - The `research_universe: real` label contradicts the demo notes.
  - Turnover at small windows was flagged for checking.
- **Post-run recommendation: `block`.**
  - The verdict is consistent with the failed tests, and nothing supports hold-out consideration.
  - The 224 vs 56 trial-count gap needs an explanation. If re-runs used edited specs or signals, that would be a peeking concern.
  - The chosen `vix_min` = 16 is the lowest value on the grid. A low threshold means being in the market almost always, so the best point is probably "hold almost always", not a fear effect.
  - The chosen point does not beat buy-and-hold (1.145 vs 1.222).
  - `pbo` = 0.0 is suspicious, and `spa` may be measured against a weak benchmark. Neither pass should count as positive evidence.
  - The Sharpe levels (strategy and benchmark) look implausibly high for real markets, which fits simulated data.
  - The reviewer could not inspect individual H-0004 ledger trials, so turnover and time-in-market checks are not done.
  - The ledger and dashboard still label these trials `real` and should mark them as demo.

## Caveats

- The data is simulated. Even on real data, one long bull market gives a small effective sample, because few independent episodes sit behind thousands of daily rows.
- All results are on the train split only.
- A rejection is a valid result. It tells us this idea did not survive the tests, which is the lab working as intended.
- This is not investment advice.

## Hold-out

The hold-out is scored once, by a human-run command, and only after human approval. `holdout_verdict` in `verdict.json` is null, so the hold-out has not been scored. This report makes no statement about its outcome.
