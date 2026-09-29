"""Synthetic L-x daily-reset fund builder (SPEC Section 4.2).

    r_fund[t] = L * r_underlying[t] - (L - 1) * r_financing[t] - expense_ratio / 252

``r_financing`` is (DFF + financing_spread) / 252. Negative ``L`` (inverse funds) uses the same
formula unchanged.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

from core.config import LabConfig
from core.data import cache
from core.data.splits import load_prices

TRADING_DAYS = 252
CORRELATION_TARGET = 0.999

# Defaults are judgment calls, not measured values; rationale in docs/decisions.md.
DEFAULT_FINANCING_SPREAD = 0.0050  # annual, added to DFF
DEFAULT_EXPENSE_RATIO = 0.0095  # annual

# Underlying used to synthesize each fund. TECL tracks a technology sector index (XLK) that is not
# in the configured universe, so it has no default underlying (pass one explicitly).
FUND_UNDERLYING = {
    "TQQQ": "QQQ",
    "QLD": "QQQ",
    "SQQQ": "QQQ",
    "SOXL": "SOXX",
    "SOXS": "SOXX",
}

ResearchUniverse = Literal["real", "synthetic_long"]


def underlying_for(fund: str) -> str:
    try:
        return FUND_UNDERLYING[fund]
    except KeyError:
        raise ValueError(
            f"no default underlying for {fund}; pass one explicitly (TECL's index is not in the "
            "configured universe)"
        ) from None


def daily_returns(prices: pd.Series) -> pd.Series:
    """Simple daily returns; a return is NaN if either day's price is missing (never spanned)."""
    return prices.pct_change(fill_method=None)


def synthetic_returns(
    underlying_returns: pd.Series,
    dff_percent: pd.Series,
    leverage: float,
    *,
    financing_spread: float = DEFAULT_FINANCING_SPREAD,
    expense_ratio: float = DEFAULT_EXPENSE_RATIO,
) -> pd.Series:
    """Daily synthetic fund returns. ``dff_percent`` is DFF in percent per annum."""
    financing = (dff_percent.reindex(underlying_returns.index) / 100 + financing_spread) / (
        TRADING_DAYS
    )
    fund = leverage * underlying_returns - (leverage - 1) * financing - expense_ratio / TRADING_DAYS
    return fund.rename(f"synthetic_{leverage:g}x")


def synthetic_prices(returns: pd.Series, start_price: float = 100.0) -> pd.Series:
    """Compound returns into a price series. Refuses NaN gaps and total wipe-outs."""
    body = returns.iloc[1:] if np.isnan(returns.iloc[0]) else returns
    if body.isna().any():
        first = body.index[body.isna()][0].date()
        raise ValueError(f"cannot compound returns across a data gap (first NaN at {first})")
    if (body <= -1).any():
        first = body.index[body <= -1][0].date()
        raise ValueError(f"synthetic fund return <= -100% on {first}; price undefined")
    return (start_price * (1 + body).cumprod()).rename(returns.name)


def research_prices(
    fund: str,
    research_universe: ResearchUniverse,
    *,
    leverage: float = 3,
    underlying: str | None = None,
    financing_spread: float = DEFAULT_FINANCING_SPREAD,
    expense_ratio: float = DEFAULT_EXPENSE_RATIO,
    cache_dir: Path | None = None,
    config: LabConfig | None = None,
) -> tuple[pd.Series, dict]:
    """Train-split price series for ``fund`` under the chosen research universe, plus metadata.

    ``real``: the fund's own adjusted closes. ``synthetic_long``: the synthetic ``leverage``-x fund
    built from the underlying's full train history. The metadata records which was used.
    """
    if research_universe == "real":
        prices = load_prices(fund, "train", cache_dir=cache_dir, config=config)[fund].dropna()
        return prices, {"research_universe": "real", "fund": fund}
    if research_universe != "synthetic_long":
        raise ValueError(f"unknown research_universe {research_universe!r}")
    underlying = underlying or underlying_for(fund)
    dff_name = cache.fred_name("DFF")
    frame = load_prices([underlying, dff_name], "train", cache_dir=cache_dir, config=config)
    under = frame[underlying].dropna()
    returns = synthetic_returns(
        daily_returns(under),
        frame[dff_name],
        leverage,
        financing_spread=financing_spread,
        expense_ratio=expense_ratio,
    )
    return synthetic_prices(returns).rename(fund), {
        "research_universe": "synthetic_long",
        "fund": fund,
        "underlying": underlying,
        "leverage": leverage,
        "financing_spread": financing_spread,
        "expense_ratio": expense_ratio,
    }


def _jsonable(value):
    """Replace non-finite floats (e.g. autocorrelation of an all-zero residual) with null."""
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _horizon_correlations(syn: pd.Series, rea: pd.Series, horizons=(1, 2, 5, 21)) -> dict:
    """Correlation of non-overlapping k-day compounded returns.

    Close-timing noise (the fund's NAV/close vs the underlying's close) is mean-reverting across
    days, so it washes out at longer horizons; a structural mismatch would not.
    """
    out = {}
    for k in horizons:
        n = len(syn) // k * k
        s_k = (1 + syn.to_numpy()[:n]).reshape(-1, k).prod(axis=1) - 1
        r_k = (1 + rea.to_numpy()[:n]).reshape(-1, k).prod(axis=1) - 1
        out[str(k)] = float(np.corrcoef(s_k, r_k)[0, 1])
    return out


@np.errstate(invalid="ignore", divide="ignore")  # zero-variance inputs give NaN, reported as null
def validate_against_real(
    synthetic: pd.Series,
    real_prices: pd.Series,
    *,
    meta: dict | None = None,
    out_path: Path | None = None,
) -> dict:
    """Compare synthetic daily returns with the real fund over their overlap.

    Reports daily return correlation, annualized tracking error, cumulative return gap, the
    residual's autocorrelation, and diagnostics (regression of real on synthetic, per-year
    correlation) to help explain a shortfall. Merged into ``results/data_validation.json``
    under the key ``<fund>_<L>x``.
    """
    real = daily_returns(real_prices)
    both = pd.concat({"synthetic": synthetic, "real": real}, axis=1, sort=True).dropna()
    if len(both) < 30:
        raise ValueError(f"overlap too short to validate ({len(both)} days)")
    syn, rea = both["synthetic"], both["real"]
    residual = rea - syn
    correlation = float(syn.corr(rea))
    slope, intercept = np.polyfit(syn.to_numpy(), rea.to_numpy(), 1)
    cum_syn = float((1 + syn).prod() - 1)
    cum_real = float((1 + rea).prod() - 1)
    by_year = {
        str(year): float(group["synthetic"].corr(group["real"]))
        for year, group in both.groupby(both.index.year)
        if len(group) >= 30
    }
    result = {
        **(meta or {}),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "overlap": {
            "start": str(both.index[0].date()),
            "end": str(both.index[-1].date()),
            "days": int(len(both)),
        },
        "daily_return_correlation": correlation,
        "correlation_target": CORRELATION_TARGET,
        "correlation_target_met": bool(correlation > CORRELATION_TARGET),
        "tracking_error_annualized": float(residual.std() * np.sqrt(TRADING_DAYS)),
        "cumulative_return": {
            "synthetic": cum_syn,
            "real": cum_real,
            "gap_real_minus_synthetic": cum_real - cum_syn,
        },
        "residual_autocorrelation": {
            f"lag{k}": float(residual.autocorr(lag=k)) for k in range(1, 6)
        },
        "diagnostics": {
            "regression_real_on_synthetic": {
                "slope": float(slope),
                "intercept_daily": float(intercept),
            },
            "correlation_by_year": by_year,
            "correlation_by_horizon_days": _horizon_correlations(syn, rea),
            "mean_daily_residual": float(residual.mean()),
        },
    }
    out_path = out_path or cache.results_dir() / "data_validation.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    existing = json.loads(out_path.read_text()) if out_path.exists() else {}
    leverage = (meta or {}).get("leverage")
    label = str(real_prices.name) if leverage is None else f"{real_prices.name}_{leverage:g}x"
    existing[label] = result
    out_path.write_text(json.dumps(_jsonable(existing), indent=2, sort_keys=True) + "\n")
    return result
