"""Test 5: parameter sensitivity.

Perturb one numeric parameter at a time of the chosen point by +/- each fraction in
``perturbations`` (20% and 40% by default), re-evaluate, and require the neighborhood to look like
the chosen point rather than a lucky spike:

* the median neighbor Sharpe is at least ``min_median_neighbor_sharpe_ratio`` times the chosen
  point's Sharpe, and
* at least ``min_fraction_neighbors_beating_benchmark`` of neighbors have a higher Sharpe than
  the benchmark.

Integer parameters are rounded to the nearest integer (neighbors that round back to the chosen
value, or to a duplicate, are dropped); zero, boolean and non-numeric parameters have no
multiplicative neighbor and are skipped. A chosen point with no neighbor, or with a non-positive
Sharpe, does not pass. ``evaluate(params)`` returns the raw daily returns of the strategy at
those parameters; it is supplied by the caller because the judge never reads hypothesis files.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

from core.config import Sensitivity
from core.judge.common import TestResult, not_evaluable, sharpe

EvaluateFn = Callable[[dict], pd.Series]


def _is_number(value) -> bool:
    return isinstance(value, int | float | np.integer | np.floating) and not isinstance(
        value, bool | np.bool_
    )


def neighbor_params(params: dict, perturbations: list[float]) -> list[dict]:
    """One-at-a-time +/- perturbations of every perturbable parameter, in a stable order."""
    out: list[dict] = []
    seen: set[tuple] = set()
    for name, value in params.items():
        if not _is_number(value) or value == 0:
            continue
        for frac in perturbations:
            for sign in (-1.0, 1.0):
                new = value * (1 + sign * frac)
                if isinstance(value, int | np.integer):
                    new = int(round(new))
                key = (name, new)
                if new == value or key in seen:
                    continue
                seen.add(key)
                out.append({**params, name: new})
    return out


def sensitivity_test(
    base_returns: pd.Series,
    benchmark_returns: pd.Series,
    params: dict,
    evaluate: EvaluateFn | None,
    rf_daily: pd.Series,
    thresholds: Sensitivity,
) -> TestResult:
    """``base_returns`` and ``benchmark_returns`` are raw daily returns (not excess of cash)."""
    threshold = thresholds.min_median_neighbor_sharpe_ratio
    if evaluate is None:
        return not_evaluable("sensitivity", "no neighbor evaluator supplied", threshold)
    neighbors = neighbor_params(params, thresholds.perturbations)
    if not neighbors:
        return not_evaluable("sensitivity", "no perturbable numeric parameter", threshold)
    rf = rf_daily.reindex(base_returns.index)
    base_sr = sharpe(base_returns - rf)
    bench_sr = sharpe(benchmark_returns.reindex(base_returns.index) - rf)
    if not np.isfinite(base_sr) or base_sr <= 0:
        return not_evaluable(
            "sensitivity",
            "chosen point has no positive Sharpe ratio",
            threshold,
            base_sharpe=base_sr,
        )
    sharpes = []
    for point in neighbors:
        ret = evaluate(point)
        sharpes.append(sharpe(ret - rf.reindex(ret.index)))
    srs = np.array(sharpes)
    ratio = float(np.median(np.nan_to_num(srs, nan=-np.inf)) / base_sr)
    beating = float(np.mean(np.nan_to_num(srs, nan=-np.inf) > bench_sr))
    passed = ratio >= threshold and beating >= thresholds.min_fraction_neighbors_beating_benchmark
    details = {
        "base_sharpe": base_sr,
        "benchmark_sharpe": bench_sr,
        "n_neighbors": len(neighbors),
        "fraction_beating_benchmark": beating,
        "fraction_beating_benchmark_threshold": thresholds.min_fraction_neighbors_beating_benchmark,
        "perturbations": list(thresholds.perturbations),
        "neighbors": [{"params": p, "sharpe": s} for p, s in zip(neighbors, sharpes, strict=True)],
    }
    return TestResult("sensitivity", ratio, threshold, passed, details)
