# Methodology

This document fills in as the project proceeds.

## Data layer (Milestone 1)

- **Prices.** yfinance adjusted close (`auto_adjust=True`, `back_adjust=False`, `repair=False`, `actions=False`, `period="max"`), i.e. total-return prices. The exact settings are stored in every cache sidecar.
- **Rates.** FRED public CSV (`DFF`, `DGS3MO`), percent per annum. Bond-market holidays that NYSE trades through are forward-filled and logged in the sidecar's `alignment_log`; prices are never filled.
- **Calendar.** Every series is reindexed to NYSE sessions between its own first and last valid date. Missing sessions stay NaN (and are reported); dates that are not sessions are dropped and counted. Returns are never computed across a missing day.
- **Synthetic fund.** `r_fund = L*r_underlying - (L-1)*r_financing - expense_ratio/252`, with `r_financing = (DFF/100 + spread)/252`. Defaults and the reasoning are in `docs/decisions.md`. `validate_against_real()` reports correlation, tracking error, cumulative gap and residual autocorrelation, plus per-year and per-horizon correlations for diagnosing a shortfall.
- **Split.** Train is everything before the embargo (the 21 NYSE sessions before `holdout_start`); the hold-out starts at `holdout_start`; the embargo belongs to neither. The cache contains train rows only.
- **Known limits.** The synthetic series tracks TQQQ with daily correlation 0.9988 (target 0.999), driven by transient timing noise rather than a structural gap (see `docs/decisions.md`). TECL has no configured underlying.

## Known limitations of access control (SPEC Section 8)

- **Hold-out.** Permission rules reduce leakage but are not a hard guarantee: hold-out-period prices are publicly downloadable, and an agent with shell access could refetch them. Mitigations: the data loader truncates at fetch time; the skeptic agent audits each run for use of post-`holdout_start` data; the ledger is reviewed by the human before any hold-out scoring; and the README states this limitation openly.
- **Per-agent write scoping.** Scoping reduces the chance that an autonomous research-loop agent edits the judge, the thresholds or the ledger, but it is not an absolute technical wall. Claude Code subagent files cannot declare path-level permission rules, so the scoping is enforced by tool lists and hook scripts. An agent given `Bash` could in principle write files by a route the hook does not recognize, and the main session is not bound by any subagent's scope. Mitigations: agents that write files get no `Bash`; the skeptic's `Bash` is restricted to test commands; the thresholds hash is stored in every verdict and trial; a test fails if any ledger line changes; and the human reviews the git diff of `core/judge/`, `config/` and `ledger/` before any hold-out scoring. The README states this limitation openly.

## Judge (Milestone 3)

Thresholds live in `config/thresholds.yaml`; its sha256 is stored in every verdict. All tests use returns in excess of the daily risk-free rate; the chosen strategy is the ledger trial with the highest in-sample Sharpe, and every ledger trial counts as a trial (N). Conventions and trade-offs are in `docs/decisions.md`.

1. **Deflated Sharpe ratio.** `DSR = Phi((SR - SR0) sqrt(T-1) / sqrt(1 - skew*SR + (kurt-1)/4 SR^2))` per period, with `SR0 = sqrt(V) ((1-g) Z(1-1/N) + g Z(1-1/(N e)))`, `V` the cross-trial variance of Sharpe ratios and `g` the Euler-Mascheroni constant. Pass: `>= 0.95`.
2. **SPA.** Hansen's superior predictive ability test through `arch.bootstrap.SPA` (stationary bootstrap, consistent p-value) with buy-and-hold as the benchmark and all comparable trials as models. Pass: `p <= 0.05`.
3. **PBO (CSCV).** The comparable trial matrix is cut into 16 blocks; over all 12,870 half/half splits the in-sample winner's out-of-sample relative rank gives a logit; PBO is the share of splits with logit `<= 0`. Fewer than 50 comparable trials: "insufficient trials", no pass. Pass: `PBO <= 0.30`.
4. **Circular-shift permutation.** The lagged position series is rotated against the fund's returns; p is the share of rotated Sharpe ratios at least the observed one. Fewer than 5,000 distinct rotations exist for a 2010-start sample, so all of them are used (see decisions). Pass: `p <= 0.05`.
5. **Parameter sensitivity.** One numeric parameter at a time at +/-20% and +/-40%; median neighbor Sharpe `>= 0.6x` the chosen point's and `>= 80%` of neighbors beating the benchmark's Sharpe.
6. **Cost and financing stress.** Costs x3 and a financing drag of `(L-1) x 200 bps` a year; strategy Sharpe minus benchmark Sharpe must stay `> 0`.
7. **Regime stability.** By calendar year and by VIX tercile: positive excess in `>= 60%` of regimes and no regime above `50%` of total excess, in both partitions.
8. **Hold-out** (`lab holdout`, never run on a rejected hypothesis): same sign of excess return as train and excess Sharpe `>= 0`; only pass/fail and a timestamp are returned.

**Validation and known behavior.** On simulated pure noise the full battery advanced 0 of 200 families (limit 9.6%); the best of 500 random variants of a null signal was rejected in 8 of 8 worlds. Power against a planted edge is modest at short samples (edge Sharpe 2.65: 40% at 1,500 days, 87% at 3,000; edge Sharpe 1.8: 27% and 50%), limited chiefly by the regime and PBO tests. A rejection therefore does not mean "no edge"; it means the edge was not demonstrated to these standards.

## Ledger, pre-registration and hold-out (Milestone 4)

`lab run` refuses a hypothesis unless its spec and signal module are committed, unchanged, and dated before the run, and every earlier trial of that hypothesis recorded the same spec hash. `ledger/trials.jsonl` is append-only, enforced by a test that walks its git history. Each hypothesis can be scored on the hold-out once: the attempt is logged in `ledger/holdout_attempts.jsonl` when the slice is decrypted, a second attempt is refused, and the frozen spec and signal are loaded from the pre-registration commit. Details and trade-offs are in `docs/decisions.md`.

## Agents and the research loop (Milestone 5)

Four subagents (`.claude/agents/`) propose and critique; deterministic code produces every number and verdict.

| Agent | Tools | May write (enforced by `.claude/hooks/path_allow.py`) |
|---|---|---|
| `hypothesis` | Read, Grep, Glob, Edit, Write | `hypotheses/*.yaml`, `hypotheses/signals/*.py` |
| `data` | Read, Grep, Glob, Edit, Write | `core/data/**`, `data/cache/**`, `results/data_validation.json` |
| `skeptic` | Read, Grep, Glob, Edit, Write, `Bash(uv run pytest ...)`, `Bash(uv run lab leakage ...)` | `results/*/review.md` |
| `report` | Read, Grep, Glob, Write | `results/*/report.md` |

Every write is checked by a `PreToolUse` hook declared in the agent's own frontmatter. The hook resolves the target path (`..` and symlinks included), requires it to match the agent's globs, and refuses `config/`, `core/judge/`, `ledger/`, `.claude/` and the hold-out files whatever the globs say. The skeptic's `Bash` is limited by a second hook to test commands with no shell control characters. `scripts/loop.sh` runs one iteration (SPEC Section 9.5) and logs each agent invocation (prompt, files touched, duration) to `logs/`. The hold-out step is reachable only for an advanced hypothesis, at an interactive terminal, after typing its id; `LAB_HOLDOUT_KEY` is never given to an agent.

**What the permission tests prove, and what they do not.** `tests/agents/` runs each agent's hook command, taken verbatim from its file, against deliberate violations (writes to the judge, thresholds, ledger, `.claude/`, hold-out files and to another agent's files; `..` and symlink escapes; malformed input), and runs the whole loop with stand-ins for the model. A live probe (`LAB_LIVE_AGENT_TESTS=1`) shows real agents launched with `--agent` refused by the same hooks. They do not prove that no route around the hooks exists: `pytest` run by the skeptic executes arbitrary test code, the hypothesis agent's Python signal modules are run later by `lab run` (so a malicious signal is code that runs with the operator's privileges, and the skeptic's read is the only review before the human commits it), and a hook is a check on tool calls, not a sandbox. The driver's after-the-fact audit of touched files, the ledger append-only test, the thresholds hash in every verdict and the human's review of the git diff are the backstops. Reading is not restricted beyond the two project-wide read denies for the hold-out slice.

**The loop proves the plumbing, not a finding.** The first end-to-end iteration was run against an isolated sandbox (its own ledger, so N in the real ledger is unchanged); see `docs/evidence/m5/`. With a sandbox ledger's handful of trials, PBO reports "insufficient trials" and every hypothesis is rejected by construction.

## Dashboard (Milestone 6)

`dashboard/` is a Vite + React + TypeScript + Recharts static site with five pages (Overview, Hypotheses, Hypothesis detail, Judge validation, Method). Every figure is produced by Python and read from JSON: `lab dashboard export` writes `results/index.json` and `results/<id>/detail.json` from the ledger, specs and verdicts; `lab dashboard build` stages only the files an index lists (never a glob) and runs the Vite build into `dashboard/dist/`. Hold-out results appear only as pass or fail and the date scored, from the ledger's attempt record. The real `results/` is empty until real research runs; the committed demo in `results/demo/` comes from a simulated universe (see `docs/decisions.md` and `docs/evidence/m6/`), not from market data, is shown in clearly labelled separate sections (DEMO badge, simulated-data banner, `/demo/:id` routes) and is never mixed into the real funnel or N. The site is unlisted and noindexed, which is reduced discoverability, not access control.

## Leverage variants and the dose-response check (Milestone 7a)

- **Variants.** `lab data variants` builds 1x, 2x, 3x, -1x, -2x and -3x synthetic funds of each underlying with the same Section 4.2 formula as the original 3x fund (negative `L` unchanged) and cross-checks the ones with a real counterpart already loaded (QLD, SQQQ, SOXS). None reaches the 0.999 daily-correlation target (0.9955, 0.9986, 0.9976); the pattern matches the TQQQ result (transient close-timing noise that washes out at longer horizons) and nothing was tuned. See `docs/decisions.md`.
- **Dose-response check** (`lab dose-response H-XXXX`, optional, not part of `lab judge`). For a hypothesis built on the vol-drag mechanism, the chosen signal's effect (excess CAGR over buy-and-hold of the same fund, or `--metric excess_sharpe`) is measured on the six synthetic variants and passed as `dose = leverage factor`, `effect = measured effect` to the generic `core/judge/dose_response.py`, which fits `effect = k * sign(dose) * |dose|^2` and requires: the log-log slope within 0.5 of 2, at least 80% of points with the predicted sign, and R-squared at least 0.8. A signal that works at its own leverage but fails is reported as "mechanism not supported". With six points and no replication these are tolerances, not significance tests, and the thresholds are judgment calls. The re-runs are diagnostics of the chosen point, not ledger trials, and the check never changes a verdict.

## Closed-end funds (Milestone 7b)

`theories/cef/` is a separate theory package that runs on the unchanged `core/engine` and `core/judge`: premium or discount to NAV as a predictor of a closed-end fund's forward return. A fund is listed under `universe.closed_end_funds` in `config/lab.yaml` and goes through the ordinary pull and split path as three series (adjusted close, unadjusted close, daily NAV from Yahoo Finance's fund and NAV symbols, checked against CEFConnect's published NAV: 243 of 244 sessions identical for ADX); the hold-out slice joins `holdout.enc` only when the captain supplies the key to a full pull. Package code reads the cached series only through `load_cef`, which cannot return a row on or after the embargo start. The signal measures the discount at the close of day t against its own trailing history (no extra lag; the engine's t-to-t+1 lag is the only one, and day-t NAV is a small timing idealization since it is published after the close), and the spec (H-0002, ADX) is pre-registered like any other, with grid values justified by the mechanism alone. N counts trials across both theory packages in the one ledger. The registered hypothesis has not been run. The NAV is a relayed sponsor figure that can be revised, and the ADX train NAV has one five-day stale run, kept and flagged. See `docs/decisions.md`.
