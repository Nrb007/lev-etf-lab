# H-0001 report: Underlying momentum filter (demo)

**This is a demo on a simulated universe.** The data comes from `scripts/build_demo_world.py`, not from market data. The spec (`hypotheses/H-0001_momentum.yaml`) says the trend-persistence effect is "planted by construction, throughout the sample", and that this is "the hypothesis expected to survive". Read every number below with that in mind.

## Result

Source: `results/H-0001/verdict.json`.

| Item | Value |
|---|---|
| train_verdict | **advance** |
| N (`n_trials`) | 224 |
| n_obs | 3597 |
| chosen_trial | H-0001-000042 |
| chosen_params | window 13, hurdle 0.03 |
| holdout_verdict | null (the hold-out has not been scored) |
| reasons | `[]` (empty) |

**There are no failing tests.** All seven tests passed on the train split:

| Test | Value | Threshold | Pass |
|---|---|---|---|
| dsr | 0.9998641890328095 | 0.95 | yes |
| pbo | 0.0 | 0.3 | yes |
| permutation | 0.003892132332499305 | 0.05 | yes |
| regime | 0.8 | 0.6 | yes |
| sensitivity | 0.9781593771471021 | 0.6 | yes |
| spa | 0.02 | 0.05 | yes |
| stress | 3.4611439660746224 | 0.0 | yes |

## What the tests mean

- **dsr (deflated Sharpe ratio):** the probability that the chosen Sharpe ratio is real once you account for how many variants were tried. It must be at least 0.95.
- **pbo (probability of backtest overfitting):** how often the best in-sample variant does worse than the median out of sample, across 12,870 splits. It must be at most 0.3.
- **permutation:** the p-value from comparing the observed Sharpe (4.687) with Sharpes from time-shifted signals. The null 95th percentile was 1.599. It must be at most 0.05.
- **regime:** the fraction of calendar years with positive excess return. It must be at least 0.6. Here 0.8 means 2011, 2019 and 2020 were negative. The largest single regime share was 0.385, against a limit of 0.5.
- **sensitivity:** the fraction of neighbouring parameter settings that still beat buy-and-hold. It must be at least 0.6. Here all 8 neighbours did (fraction 1.0 against 0.8 in the details), and the benchmark Sharpe was 1.2217.
- **spa (superior predictive ability):** a bootstrap test of whether the best of 224 models beats the benchmark by more than luck. It must be at most 0.05. The value was 0.02, the tightest pass.
- **stress:** excess performance after raising costs 3x and adding a 200 bps financing spread. It must be above 0.0.

## Why N matters

N is the number of trials counted in the multiple-testing correction. The more variants you try, the more likely it is that one looks good by chance. DSR, SPA and PBO all penalise a larger N. Here N is 224, so the best result has to clear a higher bar. The expected maximum Sharpe from luck alone was 0.2417 per period (`tests.dsr.details`), against an observed 0.2953 per period.

The spec grid is 8 windows × 7 hurdles = 56 points, but the verdict counts 224 (4 × 56). My search of `ledger/trials.jsonl` for `"hypothesis_id": "H-0001"` matched 56 lines. I did not reconcile this with 224. The skeptic also flagged the gap and did not verify it. The extra trials make the tests stricter, not looser, but the reason for the repeats is not documented in the files I read.

## Skeptic review (`results/H-0001/review.md`)

- **Pre-run recommendation: clear.** No lookahead was found by reading the signal, and `lab leakage` reported no leakage across 56 grid points. The skeptic noted the following:
  - The grid has no stated rationale.
  - The mechanism is circular, because the effect is planted.
  - The spec says `research_universe: real` but also says the run uses the simulated world.
- **Post-run recommendation: block.** The skeptic's findings:
  - A Sharpe of about 4.69 against a 1.22 benchmark is implausible for a real strategy. It reflects the simulator. The skeptic said the pass must not count as evidence for hold-out consideration.
  - Every H-0001 trial the skeptic read records `research_universe: "real"`, which conflicts with the spec notes. The skeptic could not confirm which data was read and said this needs human confirmation. If real data was read, a Sharpe of 4.7 would point to a leak or engine bug.
  - The count of 224 versus the 56-point grid.
  - The chosen hurdle of 0.03 is the largest value in the grid. The neighbour at 0.042 is outside the registered grid. The surface is flat, with neighbour Sharpes between 4.43 and 4.62.
  - The first ledger trials show extreme drawdowns (about -0.97 to -1.0) and heavy turnover at the short-window corner. The chosen trial's drawdown and turnover were not seen.
  - PBO and DSR values are extreme, which is consistent with a planted effect.
  - The negative years 2019 and 2020 are odd in a world with planted persistence.
  - The verdict is consistent with the test values shown.

## Caveats

- **Simulated data.** The effect was built into the data, so passing shows only that the pipeline can detect a planted effect. It says nothing about real markets.
- **Small effective sample.** Real leveraged-fund history is one long bull market with few independent regimes, so 3597 daily observations overstate the information in the data.
- **Train split only.** All results here are from the train split.
- **A rejection is a valid result.** An advance is not proof of anything. The skeptic's post-run `block` recommendation is recorded above.
- **The hold-out is scored once.** It is scored by a human-run command, only after human approval. `holdout_verdict` is null, so it has not been scored, and this report states no hold-out result.
- **Not investment advice.**
