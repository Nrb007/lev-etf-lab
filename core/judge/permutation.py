"""Test 4: circular-shift permutation test of the signal's timing.

The held-position series (already lagged onto the days it earns) is rotated in time against the
fund's returns. A rotation keeps the signal's autocorrelation, turnover and time in market and
destroys only its alignment with returns, so the Sharpe ratios of the rotated strategies are the
null distribution of "a signal like this, with no timing skill". The p-value is
``(1 + #{null >= observed}) / (1 + #shifts)``.

Shifts: ``min_shifts`` distinct non-zero rotations sampled without replacement. A series of T
days has only T - 1 distinct non-zero rotations, so when T - 1 <= ``min_shifts`` all of them are
used and ``full_enumeration`` is recorded (see docs/decisions.md).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from core.config import Permutation
from core.engine.metrics import TRADING_DAYS
from core.judge.common import STD_FLOOR, JudgeError, TestResult, not_evaluable

CHUNK = 256  # shifts evaluated at once; bounds memory at T x CHUNK doubles
MIN_OBS = 30


def _shifted_sharpes(
    held: np.ndarray, excess_fund: np.ndarray, cost: float, shifts: np.ndarray
) -> np.ndarray:
    """Annualized Sharpe of the strategy with ``held`` rotated forward by each shift.

    Excess return of a strategy is ``held * (fund - rf) - turnover * cost``; turnover is the
    absolute change in position from a flat book, as in ``core.engine.backtest``.
    """
    t = len(held)
    base = np.arange(t)
    out = np.empty(len(shifts))
    for start in range(0, len(shifts), CHUNK):
        chunk = shifts[start : start + CHUNK]
        h = held[(base[:, None] - chunk[None, :]) % t]
        turn = np.abs(np.diff(h, axis=0, prepend=0.0))
        ex = h * excess_fund[:, None] - turn * cost
        std = ex.std(axis=0, ddof=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            sr = np.where(std > STD_FLOOR, ex.mean(axis=0) / std, np.nan)
        out[start : start + CHUNK] = sr * np.sqrt(TRADING_DAYS)
    return out


def permutation_test(
    held: pd.Series,
    fund_returns: pd.Series,
    rf_daily: pd.Series,
    cost_bps: float,
    thresholds: Permutation,
    *,
    seed: int,
) -> TestResult:
    threshold = thresholds.max_p_value
    if not (held.index.equals(fund_returns.index) and held.index.equals(rf_daily.index)):
        raise JudgeError("permutation: positions, fund returns and risk-free must share an index")
    t = len(held)
    if t < MIN_OBS:
        return not_evaluable("permutation", f"fewer than {MIN_OBS} observations", threshold)
    h = held.to_numpy(dtype="float64")
    excess_fund = (fund_returns - rf_daily).to_numpy(dtype="float64")
    cost = cost_bps / 1e4
    observed = _shifted_sharpes(h, excess_fund, cost, np.array([0]))[0]
    if not np.isfinite(observed):
        return not_evaluable("permutation", "observed Sharpe ratio is undefined", threshold)
    full = t - 1 <= thresholds.min_shifts
    if full:
        shifts = np.arange(1, t)
    else:
        rng = np.random.default_rng(seed)
        shifts = np.sort(rng.choice(np.arange(1, t), size=thresholds.min_shifts, replace=False))
    null = _shifted_sharpes(h, excess_fund, cost, shifts)
    null = null[np.isfinite(null)]
    if len(null) == 0:
        return not_evaluable("permutation", "every rotated strategy has zero volatility", threshold)
    value = float((1 + np.sum(null >= observed)) / (1 + len(null)))
    details = {
        "observed_sharpe": observed,
        "n_shifts": len(null),
        "min_shifts": thresholds.min_shifts,
        "full_enumeration": full,
        "null_sharpe_mean": float(null.mean()),
        "null_sharpe_p95": float(np.quantile(null, 0.95)),
    }
    return TestResult("permutation", value, threshold, value <= threshold, details)
