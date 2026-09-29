# Decisions

Running log of design decisions (date, options, choice, reason). This fills in as the project proceeds.

## 2026-09-29: Python version pin

- Options: SPEC Section 2 says 3.11+; captain specified 3.12+.
- Choice: `requires-python >= 3.12`, `.python-version` and CI pinned to 3.12.
- Reason: captain's locked-in decision; supersedes the spec's 3.11+ floor.

## 2026-09-29: `config/thresholds.yaml` access rules in `.claude/settings.json`

- Options: (a) reproduce SPEC Section 8's "deny read ... `config/thresholds.yaml` edits" literally; (b) treat it as a write-deny target.
- Choice: (b). Agents may read thresholds; edits are denied via the `config/**` edit rule. No read-deny on thresholds.
- Reason: the phrasing is misplaced under the read list, and the judge's transparency rules only require that agents cannot edit thresholds. Claude Code file-permission rules only consult `Read(...)` and `Edit(...)` (an `Edit` deny covers Write and other edit tools), so write-deny is expressed as `Edit(...)`. Paths use the `/`-anchored form (project root).

## 2026-09-29: PBO minimum-trials floor

- Options: any positive integer; SPEC Section 6.1 only says it is "configurable".
- Choice: `pbo.min_trials: 50` in `config/thresholds.yaml`.
- Reason: SPEC gives no number. 50 is a placeholder-free but provisional default so CSCV with S = 16 has a meaningful trial matrix; revisit at Milestone 3 when the judge validation tests exist.

## 2026-09-29: M1 synthetic-fund defaults (financing spread, expense ratio)

- Options: SPEC Section 4.2 leaves both unspecified. (a) per-fund published expense ratios (TQQQ, SOXL, TECL each differ and changed over time); (b) one conservative constant; financing spread of 0, 25, 50 or 100 bps over DFF.
- Choice: `DEFAULT_EXPENSE_RATIO = 0.95%` and `DEFAULT_FINANCING_SPREAD = 0.50%` (both annual), overridable per call and via `lab data synth --expense-ratio/--financing-spread`. Financing accrues at `(DFF + spread) / 252` per session, matching the spec's `expense_ratio / 252`.
- Reason: 0.95% is the headline management fee these fund families charged for most of 2010-2018 (later trimmed to roughly 0.75-0.90%), so it is the conservative upper end of the published range across the whole synthetic history. 50 bps is a judgment for swap/repo financing above the policy rate; it is an estimate, not a measured figure, and the judge's financing stress (+200 bps) covers the uncertainty. Neither number is tuned against TQQQ; neither was verified against current prospectuses in this session, so a human should confirm them before they are quoted anywhere.

## 2026-09-29: M1 cache holds the train slice only

- Options: (a) cache full history in `data/raw/` and truncate on read; (b) truncate at fetch time.
- Choice: (b). `lab data pull` fetches full history, splits it at the embargo, caches only rows before `embargo_start`, and never persists post-embargo rows unencrypted. The hold-out slice goes to `data/holdout.enc` (Fernet) only when `LAB_HOLDOUT_KEY` is present in the human's shell and every series was fetched in that run; otherwise it is skipped with a warning (agent sessions never have the key). Run `--refresh` to rebuild the hold-out after a partial pull.
- Reason: SPEC Section 8 relies on the loader truncating at fetch time; `data/raw/` would be an unguarded copy of post-`holdout_start` prices. `load_prices(split="train")` additionally hard-truncates on read, so even a hand-edited cache cannot leak rows.
- The embargo removes the 21 sessions before `holdout_start` from both sides; the hold-out starts exactly at `holdout_start` (no anchor price from the embargo window is kept, so the hold-out's first day has no return; Milestone 4 must account for that).

## 2026-09-29: Return-outlier hard error exempts volatility indices

- Options: (a) enforce the +/-80% hard error on every price series; (b) enforce it on tradeable prices only, keep index spikes as warnings.
- Choice: (b). `^VIX`/`^VIX3M` (any `^` ticker) are still flagged beyond +/-40% and the count beyond +/-80% is reported, but neither is a hard error.
- Reason: VIX rose about 116% on 2018-02-05 in real, correct data. With (a) `lab data validate` would fail permanently on genuine data. Funds and underlyings keep the captain's rule: flag beyond +/-40%, hard error beyond +/-80%.

## 2026-09-29: TECL has no default underlying

- Options: add XLK to the universe; require an explicit `--underlying`; drop TECL from the synthetic builder.
- Choice: `lab data synth --fund TECL` errors and asks for `--underlying`. `config/` is human-edited only and SPEC Section 4.1 lists only QQQ, SOXX and SMH as underlyings, so no XLK history is fetched.
- Reason: TECL tracks a technology sector index that is not in the configured universe. A human should decide whether to add XLK (or accept SOXX/QQQ as a proxy) before TECL is used under `research_universe: synthetic_long`.

## 2026-09-29: M1 synthetic-vs-real result (correlation target)

- Result (from `results/data_validation.json`, train overlap 2010-02-12 to 2024-05-29, 3597 days): TQQQ vs synthetic 3x QQQ daily-return correlation **0.99880**, below the 0.999 target. Annualized tracking error 3.1%; cumulative return real 152.8x vs synthetic 149.6x. SOXL vs synthetic 3x SOXX: 0.99643, tracking error 7.2%.
- Choice: report the shortfall with its likely cause and do not tune parameters (captain's decision 5 for M1).
- Likely cause (inferred from the diagnostics, not verified against fund NAV data, which free sources do not provide): close-timing noise, not a formula error. The residual (real minus synthetic) has lag-1 autocorrelation -0.40, and the correlation rises with horizon (1-day 0.99880, 2-day 0.99946, 5-day 0.99978, 21-day 0.99993). A mean-reverting residual that washes out at longer horizons is what price-timing noise looks like: TQQQ and QQQ are two separately traded ETFs whose adjusted closes each carry their own end-of-day price noise against the index level the fund is actually reset to, and the noise reverses the next day. A wrong leverage, drift or fee would show up as a persistent gap, not as a horizon-decaying one.
- SOXL is different: its correlation does not improve with horizon (21-day 0.9956), so timing noise alone does not explain it. The likeliest cause is that SOXX and SOXL follow different semiconductor indices over parts of the sample. This was not investigated further; SOXL is not the acceptance target.
- Implication for later milestones: `synthetic_long` daily returns carry roughly 3% annualized tracking error against the real fund, mostly transient. Treat single-day precision of the synthetic series with that in mind.

## 2026-09-29: M1 plumbing choices

- `LAB_DATA_DIR` and `LAB_RESULTS_DIR` override the data and results directories; the CLI tests use them to stay out of the real cache.
- `results/data_validation.json` holds one entry per `<fund>_<L>x` key (merged across runs), each recording `research_universe`; the quality report is `results/data_quality.json`.
- `lab data synth` also caches the synthetic series as `SYNTH:<fund>:<L>x` with a sidecar so it is checked by `lab data validate` like any other series.
- Fetch history is the full available history per series (`period="max"`); observed earliest cached dates: QQQ 1999-03-10, SMH 2000-06-05, SOXX 2001-07-13, TQQQ 2010-02-11, DFF 1954-07-01. Note that yfinance's SOXX history starts in mid-2001, so `synthetic_long` for SOXL cannot include the 2000-02 drawdown; QQQ does.
- Data-quality thresholds (missing-day share 1%, stale run 5 warn / 20 error, split ratios) are module constants in `core/data/validate.py`; `config/` is human-edited only, so they are not in `lab.yaml`.

## 2026-09-29: M2 timing, turnover and cost accounting

- Options: (a) charge costs on the decision day or on the day the position starts earning; (b) measure turnover on target changes or on drift-adjusted weights (a 0.5 position drifts as the fund moves, so holding it constant really means trading daily).
- Choice: costs and turnover are booked on the day the new position starts earning (t+1), from a flat book, so the first held day pays for entry. Turnover is the absolute change in the *target* position; intra-position weight drift is ignored. The same rule applies to the strategy and to both benchmarks (buy-and-hold pays one entry cost; the 50/50 mix is treated as a constant target with no rebalancing cost).
- Reason: keeps the cost model exactly `cost_bps * |delta position|`, which is what the property tests pin down, and makes strategies and benchmarks comparable. Cost: the 50/50 benchmark is slightly flattered (a real daily-rebalanced mix would pay for drift), and a strategy holding fractional positions is too. Positions of 0 or 1, the only ones v1 signals are expected to use, are unaffected.

## 2026-09-29: M2 risk-free, Sharpe/Sortino and other metric conventions

- Choice: the daily risk-free rate is `(1 + DGS3MO/100)^(1/252) - 1`, taken on the day being earned (the loader already forward-fills bond-market holidays and logs each fill). Cash weight `(1 - position)` earns it, so a -1 position earns it on 200% of NAV; nothing in v1 uses shorts. Sharpe and Sortino are computed on returns in excess of that daily rate (Sortino: downside deviation of excess returns about 0, all days in the denominator). CAGR compounds over `n/252` years; kurtosis is excess kurtosis; a ratio whose denominator is zero (up to float noise) is NaN, stored as `null` in the ledger, never infinity. Time in market is the share of days with a non-zero position.
- Reason: SPEC Section 5.3 names the metrics but not their conventions; these are the standard ones, chosen because the strategy earns cash when flat, so excess-over-cash is the fair Sharpe. A human should confirm before results are quoted.

## 2026-09-29: M2 signal contract details

- NaN handling: leading NaNs (indicator warm-up) are flat (0); a NaN after the signal has started, or any position outside [-1, 1], is an error. Filling silently would hide bugs (consistent with the no-silent-fill rule of Section 4.1).
- Options: leakage self-test compares the truncated value with the full-history value exactly, or within a tolerance. Choice: `atol = 1e-9`, because pandas rolling windows accumulate in a history-dependent order and differ in the last bits. A real leak moves a position by far more than that; a signal thresholding a rolling statistic that lands within 1e-9 of its threshold could in principle flip, which we accept.
- The test picks 25 dates with `numpy.random.default_rng(20260929)` (captain's decision: fixed K and seed for reproducible CI), from every features date including warm-up. It runs inside `run_backtest` and cannot be disabled. The trade-off of a fixed seed is that a leak that only shows on other dates could survive; `check_leakage(..., seed=)` accepts another seed for the skeptic to use.
- The features frame passed to a signal contains `close` (the fund) plus `underlying` and `vix` when cached; the engine itself is agnostic to what the columns mean.

## 2026-09-29: M2 `lab run` before pre-registration exists

- Choice (captain's decision): `lab run H-XXXX` records real trials now (parquet in `ledger/returns/`, one line in `ledger/trials.jsonl`, N = line count). It does not check that the spec is committed, hashed or older than the run; that gate is Milestone 4. It stores `spec_hash` and `thresholds_hash` (sha256 of the file bytes) and `git_commit` so M4 can verify them later. Trial ids are `<H-id>-<N, six digits>`.
- Spec and signal loading: the spec is read with a minimal, lenient model (`id`, `universe`, `signal_module`, `params`); strict validation of all Section 7.1 fields is M4. A signal module exposes `make_signal(**params) -> Signal`; the grid is the Cartesian product of `params.*.values`. `LAB_HYPOTHESES_DIR` and `LAB_LEDGER_DIR` override the locations (tests use them).
- Failure behavior: a grid point is recorded only after it backtests cleanly. If a later point fails (for example the leakage test), earlier points stay in the ledger, since they were real trials, and the command exits non-zero. Until M4 the ledger is therefore unprotected against being polluted by hand-run test hypotheses; only `tests/` fixtures with a temporary ledger are used in this milestone, and the committed `ledger/trials.jsonl` stays empty.

## 2026-09-29: M2 runner lives outside `core/engine`

- The runner needs the fund, underlying and leverage to assemble data, and SPEC Section 1.6 forbids `core/engine` from referencing leverage or a ticker. So `core/runner.py` owns spec loading, data assembly and the ledger writes, while `core/engine` only sees a signal, a features frame, fund returns and a risk-free series.
- Also fixed a pre-existing flaky M1 test: `test_holdout_roundtrip_uses_disposable_key` asserted the ciphertext did not contain `b"QQQ"`, which base64 output contains by chance now and then; it now checks for the parquet magic `PAR1`.

## 2026-09-29: rework SPEC Section 8 access control (adopted, captain approved)

Status: adopted 2026-09-29 by the captain. Applied in the M3 PR: `.claude/settings.json` (the three blanket denies removed), SPEC.md Section 8 and its CLAUDE.md excerpt, the repo `CLAUDE.md` rule, and `docs/methodology.md`. The `.claude/agents/**` and `.claude/hooks/**` deny is applied right after M5 merges, not now. The settings.json edit was made through Bash because the file's own deny rule blocks the Edit tool; it was the captain-approved change and nothing else in the file changed.

### Problem
The project-wide `Edit(/config/**)`, `Edit(/core/judge/**)`, `Edit(/ledger/**)` denies also block supervised construction of those directories (M0-M4). A deny at any settings level cannot be overridden by another level (Claude Code permissions docs, "Settings precedence": "If a tool is denied at any level, no other level can allow it"; "An allow rule can't carve an exception out of a deny rule"), so a local `settings.local.json` allow does not help.

### What subagent files can and cannot do (from https://code.claude.com/docs/en/sub-agents, summarized by a fetch model; re-read the page before writing agent files in M5, per SPEC 0 rule 5)
- Supported frontmatter: `name, description, tools, disallowedTools, model, permissionMode, maxTurns, skills, mcpServers, hooks, memory, background, omitClaudeMd, effort, isolation, color, initialPrompt`.
- **No** path-level allow/deny rules in a subagent definition. `Edit(path)`-style rules exist only in settings files, and those apply session-wide.
- What does exist: `tools` / `disallowedTools` (whole-tool allow/deny, so an agent without `Edit`/`Write`/`Bash` cannot write at all), `permissionMode`, and `hooks` (`PreToolUse` with a `matcher`; a command hook that exits 2 blocks the call). A hook receives the tool input as JSON, so a hook script can enforce a path allowlist on `Edit`/`Write` (`tool_input.file_path`).
- Not verified: whether frontmatter hooks fire when the agent is run as the main thread (`claude --agent <name>`) as opposed to spawned as a subagent. M5 must test this by deliberate violation attempts (its acceptance criterion already requires that).

### 1. New `.claude/settings.json`
Keep, unconditional and project-wide (no agent ever needs these): `Read(/data/holdout.enc)`, `Read(/results/holdout/**)`, `Edit(/.claude/settings.json)`. Drop `Edit(/config/**)`, `Edit(/core/judge/**)`, `Edit(/ledger/**)`. Confirmed workable: nothing else in the repo depends on those three rules.
Suggested addition for you to accept or reject: also deny `Edit(/.claude/agents/**)` and `Edit(/.claude/hooks/**)` project-wide. The per-agent scoping below lives in those files; without this an agent could rewrite its own scope. It does not block human or crewmate edits through ordinary PR review any more than the settings.json rule does today, but it would block M5 crewmates who build those files, so it may be better applied only once M5 is merged.

### 2. What stops each M5 subagent from touching `core/judge/**`, `config/**`, `ledger/**`
Two layers per agent file: (a) a minimal `tools` list, (b) for every agent that has `Edit` or `Write`, a `PreToolUse` hook (matcher `Edit|Write`) running one shared script, `.claude/hooks/path_allow.py <allowed globs>`, that exits 2 for any path outside the agent's list.
- `hypothesis`: `tools: Read, Grep, Glob, Edit, Write` (no Bash). Hook allows `hypotheses/*.yaml`, `hypotheses/signals/*.py`.
- `data`: `tools: Read, Grep, Glob, Edit, Write` (no Bash; fetching is human-run as it needs the network and `LAB_HOLDOUT_KEY`). Hook allows `core/data/**`, `data/cache/**`, `results/data_validation.json`. Hold-out access stays out of scope by project-wide deny plus SPEC 9.2.
- `skeptic`: `tools: Read, Grep, Glob, Write, Bash`. Hook allows only `results/*/review.md`. Its Bash is limited by a second `PreToolUse` hook to `pytest`, `uv run pytest` and the leakage self-test; this is a command-text check, so it is a speed bump, not a wall.
- `report`: `tools: Read, Grep, Glob, Write` (no Bash). Hook allows `results/*/report.md`.
Tamper evidence that does not depend on permissions: every verdict stores the sha256 of `config/thresholds.yaml`; `lab run` stores it in each trial; the ledger-append-only test fails on any modified line; the human reviews the git diff before hold-out scoring.

### 3. SPEC Section 8 rewrite (replace the body of Section 8)
> `.claude/settings.json` denies every agent, project-wide, from reading `data/holdout.enc` and `results/holdout/**` and from editing `.claude/settings.json`. Do not export `LAB_HOLDOUT_KEY` in any agent session.
>
> Write access is scoped per agent, not per directory: each subagent file in `.claude/agents/` lists the minimal `tools` it needs and, for agents that can edit files, a `PreToolUse` hook that blocks any write outside that agent's allowed paths (Section 9). Two kinds of actor write in this repo, and the rule differs. (1) Supervised construction and maintenance sessions (a human, or a crewmate working in a task worktree; every milestone M0 onward) DO write `config/**`, `core/**` including `core/judge/**`, `ledger/**` code and `.claude/**`; their changes are reviewed like any other code through the no-mistakes pipeline and the pull request, and no settings rule blocks them. (2) The autonomous research-loop subagents of Section 9 (`hypothesis`, `data`, `skeptic`, `report`) are barred from writing `config/**`, `core/judge/**`, `ledger/**` and `.claude/**`, and may write only the paths listed in their own agent file. The trial ledger's contents (`ledger/trials.jsonl`, `ledger/returns/`) are written only by `lab run`, never by hand. Every verdict and trial records the hash of `config/thresholds.yaml`.
>
> Verify the exact permission-rule and subagent-frontmatter syntax against current Claude Code docs.
>
> **Known limitation, to be documented in `docs/methodology.md`.** (keep the existing hold-out paragraph unchanged, then add the paragraph in item 4.)

### 4. `docs/methodology.md` known-limitation note (same wording standard as the hold-out note)
> Per-agent write scoping reduces the chance that an agent edits the judge, the thresholds or the ledger, but it is not an absolute technical wall. Claude Code subagent files cannot declare path-level permission rules, so the scoping is enforced by tool lists and hook scripts. An agent given `Bash` could in principle write files by a route the hook does not recognize, and the main session is not bound by any subagent's scope. Mitigations: agents that write files get no `Bash`; the skeptic's `Bash` is restricted to test commands; the thresholds hash is stored in every verdict and trial; a test fails if any ledger line changes; and the human reviews the git diff of `core/judge/`, `config/` and `ledger/` before any hold-out scoring. The README states this limitation openly.

### Risks and open points
- Dropping the three denies removes the only mechanical barrier for the current session and for any agent run before M5's hooks exist. Until M5 lands, nothing scoped stops an agent from editing the judge; build M5 before running any autonomous loop.
- Hook scripts are code that gates security; they need their own tests (deliberate-violation tests in M5).
- The doc summary above came from a fetch model, not a verbatim read of the page; re-verify field names and hook-in-`--agent` behaviour when M5 starts.

## 2026-09-29: M3 judge conventions (returns, excess, chosen point)

- The judge works on returns in excess of the daily risk-free rate (`verdict.py` subtracts it once). "Excess Sharpe" (tests 6 and 8) is Sharpe(strategy) minus Sharpe(buy-and-hold benchmark), both excess of cash. "Excess return" (test 8) is the CAGR difference; in the regime test (7) it is the sum of daily (strategy - benchmark) returns per regime.
- The chosen strategy for `lab judge H-XXXX` is the hypothesis's trial with the highest in-sample Sharpe (the spec's `primary_metric`; ties to the earliest trial). DSR, SPA and PBO price in that selection by using every trial in the ledger (N = ledger line count). `lab judge` re-runs the chosen trial to recover its positions and refuses if the result does not match the ledger's stored returns, so the judged series is always the recorded one.
- SPA and PBO need a rectangular matrix, so they use the trials that have a return on every date of the chosen strategy's window; other trials (other universes or windows) still count in N for the DSR. PBO's "insufficient trials" applies to that comparable count.
- SPA uses Hansen's "consistent" p-value (`arch`), stationary bootstrap, 1000 replications, block size sqrt(T). These are code constants, not thresholds. The alternative, the "upper" (White reality check) p-value, is more conservative; the consistent one is the SPA the spec names.

## 2026-09-29: M3 permutation test with fewer than 5,000 distinct shifts

- Problem: the spec asks for at least 5,000 circular shifts, but a series of T days has only T - 1 distinct non-zero rotations. Real train windows are about 3,500 (from 2010) to 6,300 (synthetic from 1999) days.
- Options: (a) fail whenever T - 1 < `min_shifts`, which would fail every 2010-start research universe; (b) resample shifts with replacement up to `min_shifts`, which adds Monte Carlo draws but no information and only looks like more shifts; (c) use all distinct rotations when there are fewer than `min_shifts`, and sample `min_shifts` of them otherwise.
- Choice: (c). The result records `n_shifts` and `full_enumeration`. With T - 1 < 5000 the p-value is exact for the rotation null and has resolution 1/T.

## 2026-09-29: M3 sensitivity and stress re-evaluations are not ledger trials

- Sensitivity neighbors (one numeric parameter at a time, +/-20% and +/-40%, integers rounded) and the stressed re-runs are diagnostics of the already chosen point. Nothing is selected from them, so they add no selection bias and are not appended to the ledger, although `CLAUDE.md` says backtests go through `lab run`. They still run through `run_backtest` (leakage self-test included). Zero-valued, boolean and non-numeric parameters have no multiplicative neighbor and are skipped; a chosen point with no neighbor at all (no numeric parameter) does not pass test 5, because "nothing to perturb" is not evidence of stability.
- Financing stress is applied as a return drag of `(L - 1) * spread / 252` per day on the fund (for strategy and benchmark), with `L` from the spec's `universe.leverage`. The judge itself is asset-agnostic: it receives a `stress_fn` callable and never sees a leverage or a ticker.

## 2026-09-29: M3 regime test details

- Regimes: each calendar year, and terciles of the VIX level on the same date (ranked, so ties split evenly). Both partitions must pass both rules; the reported value is the smaller share of positive regimes, and the detail block carries both partitions. A partition whose total excess is not positive fails the "no regime over 50%" rule. If no VIX series is available the test does not pass. The module is `core/judge/regime.py` (Section 3 does not list a file for it).
- Tercile cut points use the whole train sample. This labels days for analysis only and feeds no signal, so it is not lookahead in the sense the engine guards against.

## 2026-09-29: M3 hold-out scoring path

- `holdout.py` decrypts in-process, calls a caller-supplied `run(frame)` (the frozen signal on the slice) and returns only `{hypothesis_id, holdout_verdict, scored_at}`. Full metrics go to `results/holdout/<id>.json`. Pass means: excess CAGR has the same non-zero sign as the train excess, is at least `min_excess_return`, and excess Sharpe is at least `min_excess_sharpe`.
- Features for the hold-out come from the slice alone. Splicing train history in front would run rolling windows across the 21-day embargo gap and a price discontinuity. The cost: a signal with a lookback of n days is flat for its first n hold-out days. The first hold-out day has no return (no anchor price, per the M1 decision), so returns start on the second day.
- `lab holdout` refuses unless a fresh train verdict is `advance` and `LAB_HOLDOUT_KEY` is set. The signal is loaded from the working tree, not from the pre-registration commit, and a second attempt is not refused: both belong to Milestone 4.

## 2026-09-29: M3 judge validation tests (tolerance, power target, what they show)

- Setup: each "strategy" is a family of 56 threshold signals (8 lookbacks x 7 thresholds, above the PBO floor of 50) on a simulated fund; the judge runs on the best in-sample member with N = 56 (500 in the snooping test), exactly as `lab judge` would. Noise worlds have no relation between signal and returns; planted worlds add `beta * z` to the daily return, with `z` a persistent feature the signal reads at the close. Edge size is quoted as the population Sharpe of "long when z > 0" (after costs, excess of cash), estimated on a 200,000-day sample.
- Noise test tolerance (captain asked me to choose and document): 200 independent worlds, advance rate must be at most 5% + three binomial standard errors = 5% + 4.6% = 9.6%. Three standard errors keeps the chance of a spurious CI failure under about 0.1% if the true rate were exactly 5%. Measured: 0 of 200 advanced. Because a hypothesis needs all seven tests to pass, the combined false-positive rate is far below the 5% each test targets (per-test rejections of noise: DSR 197, SPA 188, regime 187, PBO 156, permutation 126, sensitivity 110, stress 13 out of 200). A tighter cap would be more informative but 0/200 also fits any true rate up to about 1.5%, so more runs would be needed to justify one.
- Planted-edge target (chosen after a scan; thresholds are locked so the judge is not tuned): power >= 70% for edge Sharpe 2.65 at T = 3000 days. Measured power (30 worlds each): edge 1.82: 27% at T = 1500, 50% at T = 3000; edge 2.65: 40% at T = 1500, 87% at T = 3000. Weak edges (Sharpe about 1, T = 1500) advance almost never. Power is limited mainly by the regime test (a real edge must be positive in at least 60% of years and both partitions must avoid one dominant regime) and by PBO, which penalises a family of near-equivalent variants because the in-sample winner's out-of-sample rank is then close to random. This is a property of the specified thresholds, not a bug: the judge is very conservative on small samples. Quote it when interpreting rejections.
- Snooping test: 8 worlds, 500 random-parameter variants each (10 features, lookbacks 1-60, thresholds in [-1, 1]); the median best in-sample Sharpe is 1.1 and every one is rejected. The parameter naming the feature is a string so sensitivity does not try to perturb it.
- The whole file takes about 4-5 minutes. Set `LAB_JUDGE_VALIDATION_OUT=<path>` to write the measured rates and the power table as JSON for the dashboard's judge-validation page.

## 2026-09-29: M4 ledger.py / prereg.py restructuring (captain's decision)

- Options: keep ledger logic in `core/runner.py` (M2), or split it per SPEC Section 3.
- Choice: `core/ledger/ledger.py` owns every read and write of the ledger (`read_trials`, `count_trials`, `trial_matrix`, `append_trial`, the hold-out attempt log, `verify_append_only`); `core/ledger/prereg.py` owns spec hashing and git verification; `core/ledger/spec.py` holds the Section 7.1 pydantic model. `core/runner.py` and `core/judge_runner.py` only assemble inputs and call into them. The judge package itself still never touches files (Section 6), so "the judge calls the ledger" means `judge_runner.py`, the seam that already existed.
- Reason: the pre-registration gate and the one-shot rule need the same git machinery and the same ledger lock, and duplicating either in the runner would let the two drift.
- `core/ledger/spec.py` is not in Section 3's layout; a separate module keeps the model importable by both `prereg` callers without a runner import cycle.

## 2026-09-29: M4 full spec model, and what `lab run` checks

- The M2 lenient model is replaced by the Section 7.1 set, all required, unknown keys rejected (so a `thresholds:` key in a spec is an error, and a typo cannot silently drop a field). Text fields must be non-blank. `benchmark` accepts only `buy_and_hold` and `primary_metric` only `sharpe`, because those are the only ones the judge implements; widening either is a judge change. `universe.leverage` (default 3) is kept from M2, since the financing stress and the synthetic builder need it. `hypotheses/H-0000_template.yaml` is a test-validated template.
- `registered_at` is recorded but not checked against the commit date: git is the authority, and a date-only field cannot be compared to a commit timestamp without timezone guesses.
- Gate (before any backtest): spec and signal are tracked, with no staged or unstaged change (`git status --porcelain`, gitignored counts as not committed); the committer date of the latest commit touching either is strictly before the run's start time; every prior trial of that hypothesis recorded the same spec hash. Beyond Section 7.2 the signal module's hash is checked the same way (trials record `signal_hash`), because a signal edited after trials exist changes what the hypothesis means. Consequence: fixing a signal bug after `lab run` means registering a new hypothesis id; the old trials still count in N.
- Spec and signal must live in one git repository (the spec's), and the signal module is a single file: helpers it imports from elsewhere in the repo are not frozen.
- Trials now record `spec_path`, `signal_path`, `signal_hash`, `registered_commit_at`, and `git_commit` changes meaning from "HEAD" to "the latest commit touching the spec or signal", i.e. the pre-registration commit. Trials recorded before M4 (none are committed) lack these fields and cannot be frozen for the hold-out.
- Cost: a commit dated in the future (or clock skew between a committer and the runner) refuses a run; that is intended.

## 2026-09-29: M4 append-only test

- The ledger cannot forbid a hand edit at write time (it is a plain file), so the guarantee is a test: `verify_append_only` (unit-tested on modified, removed and reordered lines) plus a test that walks the git history of `ledger/trials.jsonl` and requires each version to extend the previous one, ending with the working tree. CI now checks out full history (`fetch-depth: 0`) so it has something to walk; in a shallow clone the test skips rather than pass vacuously. It cannot see edits that were never committed and it cannot detect a rewritten history, which the human's review of the ledger diff still covers.

## 2026-09-29: M4 hold-out attempt record format

- Options: (a) reuse `trials.jsonl` with a marker; (b) a separate `ledger/holdout_attempts.jsonl`.
- Choice: (b). An attempt is a different kind of event from a grid-point trial (one per hypothesis, not one per grid point), and mixing them would put non-trial lines into `count_trials()` and the trial matrix, so N would silently change.
- Format: one JSON line per event. `started` is written by `reserve_holdout_attempt` under an exclusive lock that also checks for any earlier line for the hypothesis id, so a second attempt is refused atomically, and concurrent attempts have exactly one winner. It carries the trial id, pre-registration commit, spec, signal and thresholds hashes. `finished` closes it with `pass`, `fail` or `error`. Only the pass/fail word is recorded, never a metric. The file is subject to the same append-only rule as the trial log.
- When the attempt is spent: after the slice is decrypted and before the signal runs (`score_holdout(on_decrypted=...)`), not before. A missing file or wrong key therefore costs nothing, and a rejected train verdict never reaches this point. From decryption on, any crash still counts as the one attempt (`finished: error`): the alternative, letting a crashed run retry, would let a human keep re-running until it stops crashing on a frozen signal. A human who needs to reset after a genuine infrastructure failure edits the ledger by hand and answers for it in review, which the append-only test will flag.
- `lab holdout` order: key present, no prior attempt, frozen train verdict is `advance`, then score. A refused second attempt writes nothing.

## 2026-09-29: M4 frozen signal for the hold-out

- The spec and signal are read with `git show <git_commit>:<path>` for the chosen trial, checked against the `spec_hash` and `signal_hash` that `lab run` recorded, and imported from a temporary copy. The fresh train verdict that gates the hold-out is computed from the same frozen code, and re-running the chosen trial must still reproduce the ledger returns, so a working-tree edit after registration can neither change what is scored nor what is judged.
- Limits: the frozen signal cannot import repo files that are not part of the single signal module, and a commit that has been rewritten out of the history makes `lab holdout` refuse rather than fall back to the working tree.
