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
