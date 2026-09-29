"""Test 1: deflated Sharpe ratio (Bailey and Lopez de Prado, 2014).

The probability that the chosen strategy's true Sharpe ratio is positive *after* accounting for
having picked it out of ``n_trials`` attempts and for non-normal returns. The benchmark Sharpe
is the expected maximum of ``n_trials`` Sharpe ratios drawn under the null:

    SR0 = sqrt(V) * ((1 - g) * Z(1 - 1/N) + g * Z(1 - 1/(N e))),  g = Euler-Mascheroni

with ``V`` the cross-trial variance of the (per-period) Sharpe estimates, and

    DSR = Phi( (SR - SR0) * sqrt(T - 1) / sqrt(1 - skew*SR + (kurt - 1)/4 * SR^2) )

using non-excess kurtosis. Everything is per period (daily), not annualized.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from core.config import Dsr
from core.judge.common import (
    TestResult,
    column_sharpes,
    not_evaluable,
    per_period_sharpe,
)

EULER_GAMMA = 0.5772156649015329


def expected_max_sharpe(trial_sharpes: np.ndarray, n_trials: int) -> float:
    """SR0: expected maximum per-period Sharpe among ``n_trials`` null trials.

    The variance is taken over the finite entries of ``trial_sharpes``. With one trial, or too
    few finite Sharpe ratios to estimate a variance, there is nothing to deflate by and SR0 is 0.
    """
    finite = trial_sharpes[np.isfinite(trial_sharpes)]
    if n_trials < 2 or len(finite) < 2:
        return 0.0
    var = float(finite.var(ddof=1))
    z1 = stats.norm.ppf(1 - 1 / n_trials)
    z2 = stats.norm.ppf(1 - 1 / (n_trials * np.e))
    return float(np.sqrt(var) * ((1 - EULER_GAMMA) * z1 + EULER_GAMMA * z2))


def deflated_sharpe_probability(
    returns: pd.Series, trial_returns: pd.DataFrame, n_trials: int
) -> tuple[float, dict]:
    """DSR probability and the numbers behind it. ``returns`` are excess of the risk-free rate."""
    x = returns.to_numpy(dtype="float64")
    t = len(x)
    sr = per_period_sharpe(x)
    sr0 = expected_max_sharpe(column_sharpes(trial_returns), n_trials)
    if not np.isfinite(sr):
        return float("nan"), {"n_obs": t, "n_trials": n_trials}
    skew = float(stats.skew(x, bias=False)) if t > 2 else float("nan")
    kurt = float(stats.kurtosis(x, fisher=False, bias=False)) if t > 3 else float("nan")
    radicand = 1 - skew * sr + (kurt - 1) / 4 * sr**2
    details = {
        "sharpe_per_period": sr,
        "expected_max_sharpe_per_period": sr0,
        "n_obs": t,
        "n_trials": n_trials,
        "skew": skew,
        "kurtosis": kurt,
    }
    if not np.isfinite(sr) or not np.isfinite(radicand) or radicand <= 0 or t < 4:
        return float("nan"), details
    z = (sr - sr0) * np.sqrt(t - 1) / np.sqrt(radicand)
    return float(stats.norm.cdf(z)), details


def dsr_test(
    returns: pd.Series, trial_returns: pd.DataFrame, n_trials: int, thresholds: Dsr
) -> TestResult:
    threshold = thresholds.min_probability
    if len(returns) < 4:
        return not_evaluable("dsr", "fewer than 4 observations", threshold)
    value, details = deflated_sharpe_probability(returns, trial_returns, n_trials)
    if not np.isfinite(value):
        return not_evaluable("dsr", "Sharpe ratio or its variance is undefined", threshold)
    return TestResult("dsr", value, threshold, value >= threshold, details)
