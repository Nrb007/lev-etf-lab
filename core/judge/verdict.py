"""Combine tests 1-7 into a train verdict (SPEC Section 6.2).

``advance`` only if all seven pass; otherwise ``reject`` with the failing tests in ``reasons``.
A reject never triggers hold-out scoring (the hold-out is test 8 and lives in ``holdout.py``).
Thresholds come from ``config/thresholds.yaml`` and the sha256 of that file goes into every
result. The judge reads no hypothesis files and makes no LLM calls: everything it needs arrives in
``JudgeInputs``, including the callables that re-evaluate the strategy for tests 5 and 6.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from core.config import CONFIG_DIR, Thresholds
from core.judge.common import JudgeError, TestResult
from core.judge.dsr import dsr_test
from core.judge.pbo import pbo_test
from core.judge.permutation import permutation_test
from core.judge.regime import regime_test
from core.judge.sensitivity import EvaluateFn, sensitivity_test
from core.judge.spa import spa_test
from core.judge.stress import StressFn, stress_test

JUDGE_SEED = 20260929  # default; the bootstrap and the shifts are the only random parts
TEST_ORDER = ("dsr", "spa", "pbo", "permutation", "sensitivity", "stress", "regime")


def thresholds_hash(path: Path = CONFIG_DIR / "thresholds.yaml") -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class JudgeInputs:
    """Everything the judge needs about one chosen strategy, all on the train split.

    Return series are raw daily returns (cash interest included) on one shared date index.
    ``trial_returns`` is the ledger's full trial matrix; ``n_trials`` is the ledger's N.
    ``held`` is the chosen strategy's position on the day it earns (already lagged).
    """

    hypothesis_id: str
    returns: pd.Series
    benchmark: pd.Series
    rf_daily: pd.Series
    trial_returns: pd.DataFrame
    n_trials: int
    held: pd.Series
    fund_returns: pd.Series
    cost_bps: float
    params: dict
    vix: pd.Series | None = None
    evaluate: EvaluateFn | None = None
    stress_fn: StressFn | None = None


def _check(inputs: JudgeInputs) -> None:
    index = inputs.returns.index
    same = (
        inputs.benchmark.index.equals(index)
        and inputs.rf_daily.index.equals(index)
        and inputs.held.index.equals(index)
        and inputs.fund_returns.index.equals(index)
    )
    if not same:
        raise JudgeError("returns, benchmark, risk-free, positions and fund must share an index")
    for name, s in (("returns", inputs.returns), ("benchmark", inputs.benchmark)):
        if s.isna().any():
            raise JudgeError(f"{name} contain NaN")
    if inputs.n_trials < 1:
        raise JudgeError("n_trials must be at least 1")


def run_tests(
    inputs: JudgeInputs, thresholds: Thresholds, *, seed: int = JUDGE_SEED
) -> dict[str, TestResult]:
    _check(inputs)
    rf = inputs.rf_daily
    strategy_ex = inputs.returns - rf
    benchmark_ex = inputs.benchmark - rf
    trials_ex = inputs.trial_returns.sub(rf.reindex(inputs.trial_returns.index), axis=0)
    return {
        "dsr": dsr_test(strategy_ex, trials_ex, inputs.n_trials, thresholds.dsr),
        "spa": spa_test(benchmark_ex, trials_ex, thresholds.spa, seed=seed),
        "pbo": pbo_test(trials_ex, inputs.returns.index, thresholds.pbo),
        "permutation": permutation_test(
            inputs.held,
            inputs.fund_returns,
            rf,
            inputs.cost_bps,
            thresholds.permutation,
            seed=seed + 1,
        ),
        "sensitivity": sensitivity_test(
            inputs.returns,
            inputs.benchmark,
            inputs.params,
            inputs.evaluate,
            rf,
            thresholds.sensitivity,
        ),
        "stress": stress_test(inputs.stress_fn, rf, thresholds.stress),
        "regime": regime_test(strategy_ex, benchmark_ex, inputs.vix, thresholds.regime),
    }


def judge(
    inputs: JudgeInputs,
    thresholds: Thresholds,
    thresholds_sha256: str,
    *,
    seed: int = JUDGE_SEED,
) -> dict:
    """The verdict JSON of SPEC Section 6.2, plus the seed and the thresholds hash."""
    results = run_tests(inputs, thresholds, seed=seed)
    reasons = [name for name in TEST_ORDER if not results[name].passed]
    return {
        "hypothesis_id": inputs.hypothesis_id,
        "n_trials": inputs.n_trials,
        "n_obs": len(inputs.returns),
        "tests": {name: results[name].to_dict() for name in TEST_ORDER},
        "train_verdict": "reject" if reasons else "advance",
        "reasons": reasons,
        "holdout_verdict": None,
        "thresholds_hash": thresholds_sha256,
        "seed": seed,
    }
