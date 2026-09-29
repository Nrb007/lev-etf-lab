"""Shared helpers for the judge tests (SPEC Section 6.1).

Conventions used by every module in ``core/judge``:

* Inputs are daily simple returns. Unless a function says otherwise they are already *excess of
  the daily risk-free rate*; ``verdict.py`` does that subtraction once so tests never disagree.
* Sharpe ratios are annualized with 252 sessions; the deflated Sharpe ratio is the exception and
  works per period, as in Bailey and Lopez de Prado.
* A test that cannot be evaluated (too little data, missing input) does not pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from core.engine.metrics import TRADING_DAYS

STD_FLOOR = 1e-12  # a constant series has std ~1e-19 from float noise, not a real volatility


class JudgeError(ValueError):
    """Inputs to a judge test are inconsistent (misaligned index, NaN, empty, ...)."""


def per_period_sharpe(returns: pd.Series | np.ndarray) -> float:
    """Mean over sample standard deviation (ddof=1); NaN when the volatility is ~zero."""
    x = np.asarray(returns, dtype="float64")
    if len(x) < 2:
        return float("nan")
    std = float(x.std(ddof=1))
    return float(x.mean()) / std if std > STD_FLOOR else float("nan")


def sharpe(returns: pd.Series | np.ndarray) -> float:
    """Annualized Sharpe ratio of returns that are already in excess of the risk-free rate."""
    return per_period_sharpe(returns) * np.sqrt(TRADING_DAYS)


def excess_sharpe(strategy: pd.Series, benchmark: pd.Series) -> float:
    """Sharpe of the strategy minus Sharpe of the benchmark (both already excess of cash)."""
    return sharpe(strategy) - sharpe(benchmark)


def column_sharpes(matrix: pd.DataFrame | np.ndarray) -> np.ndarray:
    """Per-period Sharpe of every column, each over its own non-NaN rows."""
    x = np.asarray(matrix, dtype="float64")
    count = np.sum(~np.isnan(x), axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.nanmean(x, axis=0)
        std = np.nanstd(x, axis=0, ddof=1)
        return np.where((count > 1) & (std > STD_FLOOR), mean / std, np.nan)


def clean_number(value) -> float | None:
    """JSON-safe float: NaN and infinity become None."""
    if value is None:
        return None
    x = float(value)
    return x if np.isfinite(x) else None


def _plain(value):
    """Recursively turn numpy scalars, NaN and tuples into JSON-safe Python values."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    if isinstance(value, bool | np.bool_):
        return bool(value)
    if isinstance(value, int | np.integer):
        return int(value)
    if isinstance(value, float | np.floating):
        return clean_number(value)
    return value


@dataclass(frozen=True)
class TestResult:
    """One test's outcome in the shape of SPEC Section 6.2.

    ``value`` is the number judged against ``threshold`` (``None`` when it could not be
    computed); ``details`` carries the supporting numbers and, when the test could not run, a
    ``reason``.
    """

    __test__ = False  # not a pytest class, despite the name

    name: str
    value: float | None
    threshold: float | None
    passed: bool
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "value": clean_number(self.value),
            "threshold": clean_number(self.threshold),
            "pass": bool(self.passed),
            "details": _plain(self.details),
        }


def not_evaluable(name: str, reason: str, threshold: float | None = None, **details) -> TestResult:
    """A test that could not run: value ``None``, not passed, with the reason recorded."""
    return TestResult(name, None, threshold, False, {"reason": reason, **details})


def comparable_trials(trial_returns: pd.DataFrame, index: pd.Index) -> pd.DataFrame:
    """Trials with a return on every date of ``index``, restricted to those dates.

    The SPA and PBO need a rectangular, NaN-free matrix. Ledger trials from other hypotheses or
    universes may cover other windows; those are left out of these two tests (they still count in
    N for the deflated Sharpe ratio).
    """
    aligned = trial_returns.reindex(index)
    return aligned.loc[:, aligned.notna().all(axis=0)]
