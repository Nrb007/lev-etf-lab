"""Performance metrics (SPEC Section 5.3). Daily returns in, annualized with 252 sessions."""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def equity_curve(returns: pd.Series) -> pd.Series:
    return (1 + returns).cumprod()


def max_drawdown(returns: pd.Series) -> float:
    """Worst peak-to-trough decline of the equity curve, as a non-positive fraction."""
    curve = equity_curve(returns)
    peak = np.maximum.accumulate(np.concatenate([[1.0], curve.to_numpy()]))[1:]
    return float((curve.to_numpy() / peak - 1).min())


def cagr(returns: pd.Series) -> float:
    growth = float(equity_curve(returns).iloc[-1])
    if growth <= 0:
        return -1.0
    return growth ** (TRADING_DAYS / len(returns)) - 1


def _safe_ratio(numerator: float, denominator: float) -> float:
    """NaN when the denominator is zero up to float noise (a constant series has std ~1e-19)."""
    return numerator / denominator if denominator > 1e-12 else float("nan")


def compute_metrics(returns: pd.Series, rf: pd.Series | None = None, *, in_market=None) -> dict:
    """All Section 5.3 metrics for one daily return series.

    ``rf`` is the daily risk-free rate on the same index; Sharpe and Sortino use returns in excess
    of it (zero if omitted). ``in_market`` is a boolean series marking days with a non-zero
    position; time in market is its mean (NaN if not supplied).
    """
    if returns.empty:
        raise ValueError("cannot compute metrics on an empty return series")
    if returns.isna().any():
        raise ValueError("returns contain NaN")
    excess = returns - (rf if rf is not None else 0.0)
    vol = float(returns.std(ddof=1)) * np.sqrt(TRADING_DAYS) if len(returns) > 1 else float("nan")
    downside = float(np.sqrt((np.minimum(excess, 0.0) ** 2).mean())) * np.sqrt(TRADING_DAYS)
    growth = cagr(returns)
    drawdown = max_drawdown(returns)
    return {
        "cagr": growth,
        "ann_vol": vol,
        "sharpe": _safe_ratio(float(excess.mean()) * TRADING_DAYS, vol),
        "sortino": _safe_ratio(float(excess.mean()) * TRADING_DAYS, downside),
        "max_drawdown": drawdown,
        "calmar": _safe_ratio(growth, -drawdown),
        "skew": float(returns.skew()),
        "kurtosis": float(returns.kurt()),  # excess kurtosis (normal = 0)
        "time_in_market": float(in_market.mean()) if in_market is not None else float("nan"),
    }
