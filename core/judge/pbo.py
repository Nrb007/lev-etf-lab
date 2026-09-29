"""Test 3: probability of backtest overfitting via CSCV (Bailey, Borwein, Lopez de Prado, Zhu).

The comparable trial matrix (T x N) is cut into ``S`` equal contiguous blocks. For each of the
C(S, S/2) ways to pick half the blocks as in-sample, the in-sample winner (best Sharpe) is ranked
among all N trials out-of-sample. With omega the relative out-of-sample rank in (0, 1) and
logit = ln(omega / (1 - omega)), PBO is the share of splits whose logit is <= 0, i.e. where the
in-sample winner lands at or below the out-of-sample median.

Below ``min_trials`` comparable trials the test reports "insufficient trials" and does not pass.
"""

from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd
from scipy import stats

from core.config import Pbo
from core.judge.common import STD_FLOOR, TestResult, comparable_trials, not_evaluable


def _block_sharpe(sums: np.ndarray, sumsq: np.ndarray, n: float) -> np.ndarray:
    """Sharpe per row from pooled sums; zero-variance columns get -inf so they never win."""
    mean = sums / n
    var = (sumsq - n * mean**2) / (n - 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        sr = mean / np.sqrt(var)
    return np.where(var > STD_FLOOR**2, sr, -np.inf)


def cscv_logits(matrix: np.ndarray, partitions: int) -> np.ndarray:
    """Logit of the in-sample winner's out-of-sample rank, one per CSCV split.

    Rows beyond a multiple of ``partitions`` (the earliest ones) are dropped so blocks are equal.
    """
    t, n = matrix.shape
    if partitions % 2 or partitions < 2:
        raise ValueError("cscv_partitions must be an even number >= 2")
    size = t // partitions
    if size < 2:
        raise ValueError(f"need at least {2 * partitions} observations for {partitions} blocks")
    x = matrix[t - size * partitions :].reshape(partitions, size, n)
    block_sum, block_sumsq = x.sum(axis=1), (x**2).sum(axis=1)
    half = partitions // 2
    combos = np.array(list(combinations(range(partitions), half)))
    in_mask = np.zeros((len(combos), partitions))
    in_mask[np.arange(len(combos))[:, None], combos] = 1.0
    out_mask = 1.0 - in_mask
    m = size * half
    sr_in = _block_sharpe(in_mask @ block_sum, in_mask @ block_sumsq, m)
    sr_out = _block_sharpe(out_mask @ block_sum, out_mask @ block_sumsq, m)
    winner = np.argmax(sr_in, axis=1)  # first index wins ties: deterministic
    winner_out = sr_out[np.arange(len(combos)), winner]
    # relative rank in (0, 1): ties share the average rank, as omega = rank / (N + 1)
    rank = np.sum(sr_out < winner_out[:, None], axis=1) + 0.5 * (
        np.sum(sr_out == winner_out[:, None], axis=1) + 1
    )
    omega = rank / (n + 1)
    return np.log(omega / (1 - omega))


def pbo_test(trial_returns: pd.DataFrame, index: pd.Index, thresholds: Pbo) -> TestResult:
    threshold = thresholds.max_pbo
    matrix = comparable_trials(trial_returns, index)
    n = matrix.shape[1]
    details = {"n_comparable_trials": n, "min_trials": thresholds.min_trials}
    if n < thresholds.min_trials:
        return not_evaluable(
            "pbo", "insufficient trials", threshold, status="insufficient_trials", **details
        )
    try:
        logits = cscv_logits(matrix.to_numpy(dtype="float64"), thresholds.cscv_partitions)
    except ValueError as exc:
        return not_evaluable("pbo", str(exc), threshold, **details)
    value = float(np.mean(logits <= 0))
    details |= {
        "partitions": thresholds.cscv_partitions,
        "n_splits": len(logits),
        "median_logit": float(np.median(logits)),
        "mean_logit": float(stats.tmean(logits)),
    }
    return TestResult("pbo", value, threshold, value <= threshold, details)
