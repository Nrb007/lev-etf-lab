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
