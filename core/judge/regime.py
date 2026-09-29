"""Test 7: regime stability.

The train period is split two ways into non-overlapping regimes: by calendar year, and by
tercile of the volatility index (VIX) on the same date. Within each partition the excess return
of a regime is the sum of daily (strategy - benchmark) returns. A partition is stable when

* at least ``min_fraction_positive_regimes`` of its regimes have positive excess, and
* no regime supplies more than ``max_single_regime_share`` of the partition's total excess
  (which must itself be positive).

Both partitions must be stable. The reported value is the smaller fraction of positive regimes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from core.config import Regime
from core.judge.common import TestResult, not_evaluable

N_TERCILES = 3


def _partition_stats(excess: pd.Series, labels: pd.Series) -> dict:
    by_regime = excess.groupby(labels, observed=True).sum()
    total = float(by_regime.sum())
    positive = float((by_regime > 0).mean())
    share = float(by_regime.max() / total) if total > 0 else float("inf")
    return {
        "n_regimes": int(len(by_regime)),
        "fraction_positive": positive,
        "max_share": share,
        "total_excess": total,
        "excess_by_regime": {str(k): float(v) for k, v in by_regime.items()},
    }


def regime_test(
    strategy: pd.Series, benchmark: pd.Series, vix: pd.Series | None, thresholds: Regime
) -> TestResult:
    threshold = thresholds.min_fraction_positive_regimes
    if vix is None:
        return not_evaluable("regime", "no VIX series supplied for the tercile split", threshold)
    vix = vix.reindex(strategy.index)
    if vix.isna().any():
        return not_evaluable("regime", "VIX is missing on some return dates", threshold)
    excess = strategy - benchmark
    years = pd.Series(excess.index.year, index=excess.index)
    terciles = pd.qcut(vix.rank(method="first"), N_TERCILES, labels=False)
    parts = {
        "year": _partition_stats(excess, years),
        "vix_tercile": _partition_stats(excess, terciles),
    }
    fractions = [p["fraction_positive"] for p in parts.values()]
    shares = [p["max_share"] for p in parts.values()]
    value = float(min(fractions))
    max_share = float(max(shares))
    passed = value >= threshold and max_share <= thresholds.max_single_regime_share
    details = {
        "max_single_regime_share": max_share if np.isfinite(max_share) else None,
        "max_single_regime_share_threshold": thresholds.max_single_regime_share,
        "partitions": parts,
    }
    return TestResult("regime", value, threshold, passed, details)
