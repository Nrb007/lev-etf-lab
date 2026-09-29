"""Test 6: cost and financing stress.

Re-run the chosen strategy and the benchmark with trading costs multiplied and the financing
spread raised, and require the excess Sharpe (strategy minus benchmark) to stay above the floor.
The judge is asset-agnostic, so *how* a stress is applied is the caller's ``stress_fn``: it
returns the stressed (strategy, benchmark) daily returns, both raw (not excess of cash).
"""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from core.config import Stress
from core.judge.common import TestResult, excess_sharpe, not_evaluable

StressFn = Callable[[float, float], tuple[pd.Series, pd.Series]]


def stress_test(stress_fn: StressFn | None, rf_daily: pd.Series, thresholds: Stress) -> TestResult:
    threshold = thresholds.min_excess_sharpe
    if stress_fn is None:
        return not_evaluable("stress", "no stress evaluator supplied", threshold)
    strategy, benchmark = stress_fn(thresholds.cost_multiplier, thresholds.financing_spread_bps)
    rf = rf_daily.reindex(strategy.index)
    value = excess_sharpe(strategy - rf, benchmark.reindex(strategy.index) - rf)
    details = {
        "cost_multiplier": thresholds.cost_multiplier,
        "financing_spread_bps": thresholds.financing_spread_bps,
    }
    if pd.isna(value):
        return not_evaluable("stress", "stressed Sharpe ratio is undefined", threshold, **details)
    return TestResult("stress", value, threshold, value > threshold, details)
