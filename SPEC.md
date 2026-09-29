# lev-etf-lab: Build Specification

A research system that generates, tests, and statistically judges hypotheses about when leveraged tech ETFs (TQQQ, SOXL, and related funds) are cheap or expensive to hold. Agents propose and critique. Deterministic code produces every number and every verdict.

**Status of claims.** This project does not replicate any specific fund's method. It is a hypothesis-driven research system built on public, free data. It is not investment advice and is not connected to any brokerage.

---

## 0. How to work on this repo

Read this section before starting any milestone.

1. Before each milestone, **ask clarifying questions first**. Then present a **short plan with tradeoffs** and wait for my choice. Write code only after that.
2. Work one milestone at a time (Section 12). Do not start the next until the acceptance criteria for the current one pass.
3. Never write a claim in code, docs, or the dashboard that the tests do not support.
4. When a design decision has a tradeoff, add a short entry to `docs/decisions.md` (date, options, choice, reason).
5. Verify current Claude Code CLI flags and subagent file format against the official docs before writing the driver or agent files. Do not rely on memory for these.

---

## 1. Principles

1. **Numbers come from code, never from an LLM.** Backtests, statistics, and verdicts are deterministic Python. Agents may read results and write prose.
2. **Pre-register everything.** A hypothesis spec is committed to git before it runs. The judge reads pass/fail thresholds from global config, which agents cannot edit.
3. **Count every trial.** Every backtest run, including each parameter-grid point, increments the trial count N used by the multiple-testing corrections.
4. **The hold-out is scored once, on final survivors only.** The judge returns pass or fail with no diagnostics to the generating agents.
5. **Rejections are results.** The dashboard shows rejected hypotheses next to survivors. A run that finds nothing is a valid outcome.
6. **Asset-agnostic core.** Nothing in `core/engine` or `core/judge` may reference leverage, a ticker, or a specific theory.

---

## 2. Tech stack

- Python 3.11+, managed with `uv`. Lint and format with `ruff`. Tests with `pytest` and `hypothesis` (property tests).
- Libraries: `pandas`, `numpy`, `scipy`, `statsmodels`, `arch` (GARCH, stationary bootstrap, SPA test), `yfinance`, `pyarrow` (parquet), `typer` (CLI), `pydantic` (spec and config validation), `pyyaml`, `cryptography` (hold-out encryption), `pandas-market-calendars`.
- FRED data via the public CSV endpoint (`https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES>`), so no API key is required.
- Dashboard: Vite + React + TypeScript, Recharts, static build.
- CI: GitHub Actions running lint and tests on push.

---

## 3. Repository layout

```
lev-etf-lab/
├── CLAUDE.md                      # contents in Section 14
├── README.md                      # written last, see Section 13
├── pyproject.toml
├── config/
│   ├── lab.yaml                   # universe, dates, costs, hold-out date (human-edited only)
│   └── thresholds.yaml            # judge pass/fail thresholds (human-edited only)
├── core/                          # deterministic, no LLM calls
│   ├── data/
│   │   ├── loaders.py             # yfinance + FRED, caching
│   │   ├── synthetic.py           # synthetic L-x fund builder
│   │   ├── splits.py              # train / hold-out separation
│   │   └── validate.py            # data quality checks
│   ├── engine/
│   │   ├── backtest.py            # signal in, returns and costs out
│   │   ├── metrics.py             # Sharpe, drawdown, turnover, etc.
│   │   └── signal_api.py          # Signal protocol and lag enforcement
│   ├── judge/
│   │   ├── dsr.py                 # deflated Sharpe ratio
│   │   ├── spa.py                 # SPA / reality check wrapper
│   │   ├── pbo.py                 # CSCV probability of backtest overfitting
│   │   ├── permutation.py         # circular-shift and bootstrap tests
│   │   ├── sensitivity.py         # parameter-surface checks
│   │   ├── stress.py              # cost, financing, and regime stress
│   │   ├── holdout.py             # one-shot hold-out scoring
│   │   └── verdict.py             # combines tests via thresholds.yaml
│   ├── ledger/
│   │   ├── ledger.py              # append-only trial log
│   │   └── prereg.py              # spec hashing, git-commit verification
│   └── cli.py                     # `lab` entry point
├── hypotheses/
│   ├── H-0000_template.yaml
│   └── signals/                   # one Python module per hypothesis
├── data/                          # gitignored
│   ├── raw/
│   ├── cache/                     # train-period parquet only
│   └── holdout.enc                # encrypted hold-out slice
├── results/                       # JSON per run, committed; consumed by dashboard
├── ledger/
│   ├── trials.jsonl               # append-only
│   └── returns/                   # parquet of each trial's return series
├── .claude/
│   ├── settings.json              # permission rules, see Section 8
│   └── agents/
│       ├── hypothesis.md
│       ├── data.md
│       ├── skeptic.md
│       └── report.md
├── scripts/
│   └── loop.sh                    # headless driver, see Section 9
├── dashboard/                     # static site
├── docs/
│   ├── decisions.md
│   └── methodology.md
└── tests/
```

---

## 4. Data layer (`core/data`)

### 4.1 Sources and universe

Configured in `config/lab.yaml`. Initial universe:

| Role | Tickers |
|---|---|
| Underlyings | QQQ, SOXX (also SMH as a cross-check) |
| 3x long funds | TQQQ, SOXL, TECL |
| Other leverage (for later extension, load but do not use in v1 hypotheses) | QLD (2x), SQQQ (-3x), SOXS (-3x) |
| Volatility | ^VIX (also ^VIX3M if available) |
| Rates | FRED `DFF` (effective fed funds rate), `DGS3MO` |

Rules:

- Use total-return prices (adjusted close). Record the exact adjustment settings in the cache metadata.
- Cache to parquet with a metadata sidecar (source, fetch time, row count, content hash). Re-fetch only on explicit request.
- Use the NYSE trading calendar. Align all series to it and log every gap or forward-fill. Never silently fill.

### 4.2 Synthetic L-x fund builder (`synthetic.py`)

Build a synthetic daily-reset fund from an underlying's daily returns:

```
r_fund[t] = L * r_underlying[t]
            - (L - 1) * r_financing[t]     # financing at fed funds + configurable spread
            - expense_ratio / 252
```

- `L`, the financing spread, and the expense ratio are parameters. Support negative `L` (inverse funds) from the start, even though v1 hypotheses use `L = 3`.
- Provide a `validate_against_real()` routine comparing a synthetic series to the real fund over their overlap: daily return correlation, annualized tracking error, cumulative return gap, and the residual's autocorrelation. Write the result to `results/data_validation.json`.
- Acceptance target: daily return correlation above 0.999 for TQQQ vs synthetic 3x QQQ. If it is not met, stop and report the likely cause instead of tuning parameters to force a fit.
- Add a `research_universe` option: `real` (fund history only, from about 2010) or `synthetic_long` (synthetic 3x from the underlying's full history, which includes the 2000-02 drawdown). Every result records which one was used.

### 4.3 Train / hold-out split (`splits.py`)

- `holdout_start` is set in `config/lab.yaml` (default `2024-07-01`) with an embargo of 21 trading days before it that is excluded from both sides.
- Fetching writes the hold-out slice to `data/holdout.enc` (Fernet-encrypted). The key comes from the environment variable `LAB_HOLDOUT_KEY`, which is set only in the human's shell and the human-run driver, never in agent sessions.
- `load_prices(..., split="train")` is the only loader agents and hypothesis code can use. It must be structurally incapable of returning post-`holdout_start` rows, enforced by a hard truncation plus a test.
- Only `core/judge/holdout.py` may decrypt the hold-out slice.

### 4.4 Data quality checks (`validate.py`)

Missing days, zero or negative prices, splits or reverse splits (leveraged funds have had many), return outliers beyond a configurable threshold, and stale prices. Output a machine-readable report and fail loudly on hard errors.

---

## 5. Backtest engine (`core/engine`)

### 5.1 Signal interface

A hypothesis signal module exposes:

```python
class Signal(Protocol):
    name: str
    params: dict
    def compute(self, features: pd.DataFrame) -> pd.Series:
        """Target position in [-1, 1] (v1: [0, 1]), indexed by date.
        Must use only information available at the close of that date."""
```

### 5.2 Lag enforcement

- The engine applies each day's target position to the **next** trading day's return. Signal authors cannot control this lag.
- Include a leakage self-test: for any signal, recompute it on data truncated at each of K random dates and confirm the value at the truncation date is unchanged. A signal that changes fails with a clear error naming the date.

### 5.3 Execution model

- Costs: `cost_bps` per unit of turnover, default 5 bps, configurable in `lab.yaml`.
- Out-of-position days earn the daily risk-free rate (FRED `DGS3MO`, converted to daily).
- Optional position sizing bounds and a maximum turnover setting.
- Output per run: daily strategy returns, positions, turnover, costs paid, and metrics (CAGR, annualized vol, Sharpe, Sortino, max drawdown, Calmar, skew, kurtosis, time in market).
- Always compute benchmarks alongside: buy-and-hold of the same fund, and a 50% fund / 50% cash constant mix.

### 5.4 Runner

`lab run H-XXXX` executes the hypothesis's parameter grid. Every grid point:

1. Is backtested on the train split.
2. Writes its return series to `ledger/returns/` and one line to `ledger/trials.jsonl`.
3. Increments N.

---

## 6. Judge (`core/judge`)

The judge takes a strategy's return series, the full matrix of all trial return series in the ledger, N, and `thresholds.yaml`. It returns a structured verdict. It never reads or writes hypothesis files, and it contains no LLM calls.

### 6.1 Tests

| # | Test | Method | Default threshold (`thresholds.yaml`) |
|---|---|---|---|
| 1 | Deflated Sharpe ratio | Bailey and Lopez de Prado. Expected max Sharpe under the null from N trials and the cross-trial Sharpe variance, then adjust for T, skew, and kurtosis | DSR probability >= 0.95 |
| 2 | SPA / reality check | `arch.bootstrap.SPA` against the buy-and-hold benchmark, using all trials as the model set, stationary bootstrap | p <= 0.05 |
| 3 | PBO via CSCV | Combinatorially symmetric cross-validation over the trial matrix, S = 16 partitions | PBO <= 0.30. Report "insufficient trials" and do not pass if N is under a configurable minimum |
| 4 | Circular-shift permutation | Shift the signal in time relative to returns (preserving its autocorrelation), rebuild the Sharpe distribution over at least 5,000 shifts | p <= 0.05 |
| 5 | Parameter sensitivity | Evaluate the grid neighborhood around the chosen point (plus and minus 20% and 40% per parameter) | Median neighbor Sharpe >= 0.6x base, and >= 80% of neighbors beat the benchmark |
| 6 | Cost and financing stress | Costs x3, financing spread +200 bps | Excess Sharpe still > 0 |
| 7 | Regime stability | Split train into non-overlapping regimes (by year, and by VIX tercile) | Positive excess in >= 60% of regimes, and no single regime contributes more than 50% of total excess return |
| 8 | Hold-out | See 6.3 | Same sign of excess return, and excess Sharpe >= 0 |

Tests 1 to 7 run on the train split. Test 8 runs only through the hold-out CLI.

### 6.2 Verdict

`verdict.py` returns:

```json
{
  "hypothesis_id": "H-0007",
  "n_trials": 412,
  "tests": { "dsr": {"value": 0.71, "threshold": 0.95, "pass": false}, "...": {} },
  "train_verdict": "reject",
  "reasons": ["dsr", "pbo"],
  "holdout_verdict": null
}
```

- `train_verdict` is `advance` only if tests 1 to 7 all pass. Otherwise it is `reject`, with the failing tests listed.
- A `reject` never triggers hold-out scoring.
- Thresholds are read from `config/thresholds.yaml`. The hash of that file is stored in every result.

### 6.3 Hold-out (`holdout.py`)

- `lab holdout H-XXXX` decrypts the hold-out slice in-process, runs the frozen signal (loaded from the git commit that pre-registered it) with its chosen parameters, and returns **only** pass or fail plus a timestamp.
- Each hypothesis can be scored on the hold-out at most once. The ledger records the attempt. A second attempt is refused.
- No metrics, curves, or diagnostics are printed, logged, or returned to any agent-accessible output. The full hold-out metrics go to `results/holdout/<id>.json`, which is in the deny list for agents and is read only by the dashboard build step run by a human.

### 6.4 Judge validation tests (required)

These live in `tests/judge/` and must pass in CI:

1. **Noise test.** Generate 200 strategies on pure Gaussian noise returns. Assert the fraction the judge advances is at or below the nominal false-positive target (about 5%, with a Monte Carlo tolerance).
2. **Planted-edge test.** Inject a signal with a known Sharpe. Assert it is advanced at a rate above a target power, and report the power as a function of edge size and T.
3. **Snooping test.** Run 500 random-parameter variants of a null signal, pick the best in-sample, and assert the judge rejects it.
4. **Determinism.** The same inputs and seed produce identical verdicts.

---

## 7. Ledger and pre-registration (`core/ledger`)

### 7.1 Hypothesis spec (`hypotheses/H-XXXX_<slug>.yaml`)

Validated by a pydantic model. Required fields:

```yaml
id: H-0007
title: Vol-drag regime filter on TQQQ
mechanism: >
  Written rationale: why this should predict forward holding-period returns.
  Must state the economic or structural mechanism. "Backtest looked good" is invalid.
universe: {fund: TQQQ, underlying: QQQ, research_universe: real}
signal_module: hypotheses/signals/h0007_voldrag.py
params:
  vol_lookback: {values: [10, 20, 40]}
  vol_threshold: {values: [0.25, 0.30, 0.35]}
benchmark: buy_and_hold
primary_metric: sharpe
registered_at: 2026-10-02
notes_on_prior_trials: >
  Which earlier hypotheses this builds on, and any peeking that already happened.
```

Thresholds are **not** part of the spec. They come from `config/thresholds.yaml`.

### 7.2 Enforcement (`prereg.py`)

`lab run` refuses to start unless:

1. The spec file and signal module are committed, with no uncommitted changes.
2. The spec's git commit date precedes the run timestamp.
3. The spec hash in the ledger matches the file.

### 7.3 Trial log

`ledger/trials.jsonl` is append-only, one JSON object per grid point: hypothesis id, params, spec hash, thresholds hash, git commit, timestamp, train-period metrics, and a pointer to the return series. The ledger module exposes `count_trials()` and `trial_matrix()` for the judge. Add a test that fails if any existing line is modified.

---

## 8. Hold-out and access control

`.claude/settings.json` denies every agent, project-wide and unconditionally, from reading the hold-out material and from editing the settings file itself:

- Deny read access to `data/holdout.enc` and `results/holdout/**`.
- Deny edits to `.claude/settings.json`.
- Do not export `LAB_HOLDOUT_KEY` in any agent session.

Write access elsewhere is scoped per agent, not per directory. Two kinds of actor write in this repo, and the rule differs. (1) Supervised construction and maintenance sessions (a human, or a crewmate working in a task worktree; every milestone) DO write `config/**`, `core/**` including `core/judge/**`, ledger code and `.claude/**`. Their changes are reviewed like any other code through the no-mistakes pipeline and the pull request, and no settings rule blocks them. (2) The autonomous research-loop subagents of Section 9 (`hypothesis`, `data`, `skeptic`, `report`) are barred from writing `config/**`, `core/judge/**`, `ledger/**` and `.claude/**`, and may write only the paths listed in their own agent file. Each agent file lists the minimal `tools` it needs and, for agents that can edit files, a `PreToolUse` hook that blocks any write outside that agent's allowed paths. Claude Code subagent files cannot declare path-level permission rules, so hooks are the mechanism. The trial ledger's contents (`ledger/trials.jsonl`, `ledger/returns/`) are written only by `lab run`, never by hand. Every verdict and trial records the hash of `config/thresholds.yaml`.

Once Milestone 5 is merged, `.claude/settings.json` also denies edits to `.claude/agents/**` and `.claude/hooks/**`, so an agent cannot rewrite its own scope.

Verify the exact permission-rule and subagent-frontmatter syntax against current Claude Code docs.

**Known limitation, to be documented in `docs/methodology.md`.** Permission rules reduce leakage but are not a hard guarantee: hold-out-period prices are publicly downloadable, and an agent with shell access could refetch them. Mitigations: the data loader truncates at fetch time; the skeptic agent audits each run for use of post-`holdout_start` data; the ledger is reviewed by the human before any hold-out scoring; and the README states this limitation openly.

---

## 9. Agents (`.claude/agents/*.md`)

Each agent is a subagent file with a narrow role and minimal tool access. Verify the frontmatter format against the current docs.

### 9.1 `hypothesis`

- **Job:** propose new hypothesis specs and signal modules, grounded in a stated mechanism (vol drag scaling with L squared, rebalancing flows, financing costs, regime persistence, and so on).
- **Reads:** train-split data via `load_prices`, prior specs, the aggregate ledger summary (N, pass/fail counts per family, but not hold-out results).
- **Writes:** only `hypotheses/*.yaml` and `hypotheses/signals/*.py`.
- **Must:** limit each spec to a small parameter grid, cite the mechanism, and avoid re-proposing near-duplicates of rejected specs.
- **Must not:** touch `core/`, `config/`, `ledger/`, or anything hold-out-related.

### 9.2 `data`

- **Job:** maintain the data layer: fetching, caching, validation, synthetic-fund checks, and reporting data problems.
- **Writes:** `core/data/**`, `data/cache/**`, `results/data_validation.json`.
- **Must not:** implement or change hold-out access.

### 9.3 `skeptic`

- **Job:** adversarial review at two points. **Pre-run:** read the spec and signal code and check for lookahead, an unjustified parameter count, a missing mechanism, post-hoc universe selection, unrealistic cost assumptions, and a same-day-close execution assumption. **Post-run:** read the verdict JSON and flag anything suspicious (a very high Sharpe, an implausible turnover, one regime carrying the result).
- **Tools:** read-only, plus permission to run tests and the leakage self-test.
- **Output:** a structured review appended to `results/<id>/review.md`, with a `block` or `clear` recommendation. `block` prevents `lab run` until the human overrides it.

### 9.4 `report`

- **Job:** turn verdict JSON and results into plain-language write-ups for the dashboard and README: why a hypothesis passed or failed, what the numbers mean, and honest caveats.
- **Must not** change or reinterpret a verdict. It reports what the judge returned, including the exact failing tests.
- **Writes:** `results/<id>/report.md` only.

### 9.5 Orchestration (`scripts/loop.sh`)

A headless driver, run by the human, that executes one loop iteration:

1. `hypothesis` proposes N_new specs.
2. `skeptic` pre-run review. Stop on `block`.
3. Human-visible checkpoint: commit the specs. (Pre-registration requires a git commit before the run.)
4. `lab run` for each cleared spec.
5. `lab judge` for each. Advance or reject.
6. `skeptic` post-run review.
7. `lab holdout` only for advanced hypotheses the human has approved.
8. `report` writes results.
9. `lab dashboard build`.

Develop the loop interactively first. Move to the headless script only when the interactive flow works end to end. Log every agent invocation (prompt, files touched, duration) to `logs/`.

---

## 10. CLI (`lab`)

```
lab data pull [--refresh]
lab data validate
lab data synth --fund TQQQ --leverage 3
lab run H-XXXX
lab judge H-XXXX
lab holdout H-XXXX              # one-shot, human-run
lab ledger summary
lab report H-XXXX
lab dashboard build
```

All commands are idempotent where possible, exit non-zero on failure, and print machine-readable output when `--json` is passed.

---

## 11. Dashboard (`dashboard/`)

Static site reading JSON from `results/`, built with Vite + React + TypeScript + Recharts. Deployed as a static site (GitHub Pages or similar).

Pages:

1. **Overview.** A funnel: proposed, passed skeptic, passed judge (train), passed hold-out. Total trials N. A plain-language explanation of why N matters.
2. **Hypotheses.** A sortable table with verdict badges (advance / reject / holdout pass / holdout fail) and failing tests per row. Rejected rows are shown by default.
3. **Hypothesis detail.** Mechanism text, equity curve versus benchmark, drawdown plot, test battery with values against thresholds, parameter-sensitivity heatmap, regime breakdown, and the report agent's write-up.
4. **Judge validation.** The noise, planted-edge, and snooping test results: false-positive rate and power curves.
5. **Method.** How the system works, the data limitations (one long bull market, small effective sample), the hold-out limitation from Section 8, and the "not investment advice" statement.

Hold-out metrics appear only as pass or fail plus the date scored.

---

## 12. Build order and acceptance criteria

| # | Milestone | Done when |
|---|---|---|
| M0 | Scaffold: repo, `uv` env, CI, CLI skeleton, config schemas, docs stubs | `pytest` and `ruff` pass in CI; `lab --help` works |
| M1 | Data layer and synthetic builder | Cache works; data-quality report generated; synthetic 3x QQQ vs TQQQ meets the correlation target or a documented explanation exists; train/hold-out split enforced by test |
| M2 | Backtest engine | Lag enforcement and leakage self-test pass; benchmarks computed; property tests on the cost model pass |
| M3 | Judge | All eight tests implemented; all four validation tests in 6.4 pass; thresholds read from config |
| M4 | Ledger, pre-registration, hold-out | `lab run` refuses uncommitted specs; ledger append-only test passes; hold-out one-shot behavior tested |
| M5 | Agents and loop | Four agent files in place; one full interactive loop iteration completed end to end; permission rules verified by deliberate attempts to violate them |
| M6 | Dashboard | All five pages render from real `results/`; rejected hypotheses visible; deployed |
| M7 | Extensions | Other leverage factors and inverse funds added with the dose-response check (Section 15); closed-end fund module added as a separate theory package |

---

## 13. Documentation deliverables

- `README.md`: what the project is and is not, an architecture diagram, how to run it, the headline result (including if the result is "nothing survived"), and the limitations.
- `docs/methodology.md`: the math for each test, the reasoning behind the thresholds, the data limitations, the hold-out limitation, and multiple-testing accounting.
- `docs/decisions.md`: running log of design decisions.

---

## 14. `CLAUDE.md` contents

```
# lev-etf-lab
Read SPEC.md first. Rules that always apply:
- Ask clarifying questions and present a plan with tradeoffs before writing code.
- Numbers and verdicts come from core/ code only. Never estimate or hand-write results.
- Never read, list, or reference data/holdout.enc or results/holdout/.
- Autonomous research-loop agents never edit config/, core/judge/, ledger/, or .claude/. Supervised construction sessions may, through the normal PR review.
- Every backtest goes through `lab run` so it is counted in the ledger.
- Signals use only information available at the close of day t.
- One milestone at a time; check acceptance criteria before moving on.
```

---

## 15. Extensions (M7 detail)

**Leverage factor and inverse funds.** Add 1x, 2x, -1x, -2x, and -3x versions of the same underlyings. Add a dose-response check to the judge as an optional test module: for a signal built on the vol-drag mechanism, effect size should scale roughly with L squared, and inverse funds should show the reversed sign. A signal that works on 3x but ignores this pattern is flagged as "mechanism not supported".

**Closed-end funds.** Separate theory package (`theories/cef/`) reusing `core/engine` and `core/judge` unchanged. Daily NAV is public for many CEFs, so premium/discount to NAV is measurable with free data. This module demonstrates that the framework is not tied to one theory.

**Trial accounting across extensions.** N counts all trials across all theory packages in one ledger. Adding a theory raises N and makes passing harder, which is intended.

---

## 16. Non-goals

- No live trading, order routing, or brokerage integration.
- No intraday or options data in v1.
- No claim of replicating any fund's proprietary method.
- No optimization of parameters on the hold-out under any circumstances.
