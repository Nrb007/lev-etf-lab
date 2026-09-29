"""Test 2: Hansen's superior predictive ability (SPA) test, a refinement of White's reality check.

Null hypothesis: no trial beats the benchmark. All comparable trials in the ledger form the model
set, so picking the best of many is priced in. Uses ``arch.bootstrap.SPA`` with a stationary
bootstrap and the "consistent" p-value (Hansen 2005).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from arch.bootstrap import SPA

from core.config import Spa
from core.judge.common import STD_FLOOR, TestResult, comparable_trials, not_evaluable

REPS = 1000  # bootstrap replications; resolution of the p-value is about 1/REPS
MIN_OBS = 30


def spa_p_value(
    benchmark: pd.Series, trial_returns: pd.DataFrame, *, seed: int, reps: int = REPS
) -> tuple[float, dict]:
    """SPA p-value with returns as (negative) losses; returns are excess of the risk-free rate."""
    models = comparable_trials(trial_returns, benchmark.index)
    diff_std = (models.sub(benchmark, axis=0)).std(axis=0, ddof=1)
    models = models.loc[:, diff_std > STD_FLOOR]  # a model identical to the benchmark adds nothing
    details = {"n_models": int(models.shape[1]), "n_obs": len(benchmark), "reps": reps}
    if models.shape[1] == 0:
        return float("nan"), details
    block = max(1, int(round(np.sqrt(len(benchmark)))))
    spa = SPA(
        -benchmark.to_numpy(),
        -models.to_numpy(),
        block_size=block,
        reps=reps,
        bootstrap="stationary",
        studentize=True,
        seed=seed,
    )
    spa.compute()
    p = spa.pvalues
    details |= {"block_size": block, "p_lower": float(p["lower"]), "p_upper": float(p["upper"])}
    return float(p["consistent"]), details


def spa_test(
    benchmark: pd.Series, trial_returns: pd.DataFrame, thresholds: Spa, *, seed: int
) -> TestResult:
    threshold = thresholds.max_p_value
    if len(benchmark) < MIN_OBS:
        return not_evaluable("spa", f"fewer than {MIN_OBS} observations", threshold)
    value, details = spa_p_value(benchmark, trial_returns, seed=seed)
    if not np.isfinite(value):
        return not_evaluable("spa", "no comparable trial differs from the benchmark", threshold)
    return TestResult("spa", value, threshold, value <= threshold, details)
