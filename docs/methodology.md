# Methodology

This document fills in as the project proceeds.

## Data layer (Milestone 1)

- **Prices.** yfinance adjusted close (`auto_adjust=True`, `back_adjust=False`, `repair=False`, `actions=False`, `period="max"`), i.e. total-return prices. The exact settings are stored in every cache sidecar.
- **Rates.** FRED public CSV (`DFF`, `DGS3MO`), percent per annum. Bond-market holidays that NYSE trades through are forward-filled and logged in the sidecar's `alignment_log`; prices are never filled.
- **Calendar.** Every series is reindexed to NYSE sessions between its own first and last valid date. Missing sessions stay NaN (and are reported); dates that are not sessions are dropped and counted. Returns are never computed across a missing day.
- **Synthetic fund.** `r_fund = L*r_underlying - (L-1)*r_financing - expense_ratio/252`, with `r_financing = (DFF/100 + spread)/252`. Defaults and the reasoning are in `docs/decisions.md`. `validate_against_real()` reports correlation, tracking error, cumulative gap and residual autocorrelation, plus per-year and per-horizon correlations for diagnosing a shortfall.
- **Split.** Train is everything before the embargo (the 21 NYSE sessions before `holdout_start`); the hold-out starts at `holdout_start`; the embargo belongs to neither. The cache contains train rows only.
- **Known limits.** The synthetic series tracks TQQQ with daily correlation 0.9988 (target 0.999), driven by transient timing noise rather than a structural gap (see `docs/decisions.md`). TECL has no configured underlying.
