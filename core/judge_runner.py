"""``lab judge`` and ``lab holdout``: assemble the judge's inputs from the ledger and the spec.

``core/judge`` never reads hypothesis files, so this module (like ``core/runner.py``) is the seam:
it loads the spec and signal, picks the chosen trial, re-runs it to recover its positions, and
hands the judge plain series plus two callables for the tests that must re-evaluate the strategy.
Those re-evaluations (parameter neighbors, stressed costs) are diagnostics of the chosen point,
not selections, so they are not ledger trials.

Financing stress is applied as a drag of ``(L - 1) * spread / 252`` per day on the fund's return,
for the strategy and the benchmark alike; ``L`` is the spec's ``universe.leverage``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from core.config import CONFIG_DIR, load_thresholds
from core.data import cache
from core.data.synthetic import daily_returns, synthetic_returns
from core.engine.backtest import BacktestResult, ExecutionConfig, daily_risk_free, run_backtest
from core.engine.metrics import TRADING_DAYS, cagr
from core.judge.holdout import score_holdout
from core.judge.verdict import JUDGE_SEED, JudgeInputs, judge, thresholds_hash
from core.ledger import ledger
from core.runner import (
    RF_SERIES,
    HypothesisSpec,
    RunError,
    build_inputs,
    find_spec,
    load_signal_factory,
    load_spec,
)

LEDGER_MATCH_ATOL = 1e-10


@dataclass(frozen=True)
class Context:
    spec: HypothesisSpec
    factory: object
    chosen: dict
    config: ExecutionConfig
    features: pd.DataFrame
    returns: pd.Series
    rf: pd.Series
    result: BacktestResult


def choose_trial(trials: list[dict]) -> dict:
    """The best in-sample trial by Sharpe (the primary metric); ties go to the earliest trial."""
    scored = [t for t in trials if t["metrics"].get("sharpe") is not None]
    if not scored:
        raise RunError("no trial has a defined Sharpe ratio")
    return max(scored, key=lambda t: (t["metrics"]["sharpe"], -t["n"]))


def _config_from(record: dict) -> ExecutionConfig:
    return ExecutionConfig(**record["execution"])


def prepare(hypothesis_id: str) -> Context:
    spec_path = find_spec(hypothesis_id)
    spec = load_spec(spec_path)
    if spec.id != hypothesis_id:
        raise RunError(f"{spec_path.name} declares id {spec.id}, expected {hypothesis_id}")
    trials = [t for t in ledger.read_trials() if t["hypothesis_id"] == hypothesis_id]
    if not trials:
        raise RunError(f"{hypothesis_id} has no trials in the ledger; run `lab run` first")
    chosen = choose_trial(trials)
    factory = load_signal_factory(spec)
    features, returns, rf, _ = build_inputs(spec)
    config = _config_from(chosen)
    result = run_backtest(factory(**chosen["params"]), features, returns, rf, config)
    stored = pd.read_parquet(ledger.ledger_dir() / chosen["returns_path"])["return"]
    if not stored.index.equals(result.returns.index) or not np.allclose(
        stored.to_numpy(), result.returns.to_numpy(), rtol=0, atol=LEDGER_MATCH_ATOL
    ):
        raise RunError(
            f"{chosen['trial_id']}: re-running the chosen trial does not reproduce the ledger "
            "returns (data, signal or engine changed since `lab run`)"
        )
    return Context(spec, factory, chosen, config, features, returns, rf, result)


def _drag(spec: HypothesisSpec, spread_bps: float) -> float:
    return (spec.universe.leverage - 1) * spread_bps / 1e4 / TRADING_DAYS


def judge_inputs(ctx: Context) -> JudgeInputs:
    spec, factory, chosen = ctx.spec, ctx.factory, ctx.chosen

    def run(params: dict, config: ExecutionConfig, drag: float = 0.0) -> BacktestResult:
        return run_backtest(factory(**params), ctx.features, ctx.returns - drag, ctx.rf, config)

    def evaluate(params: dict) -> pd.Series:
        return run(params, ctx.config).returns

    def stress_fn(cost_multiplier: float, spread_bps: float):
        config = replace(ctx.config, cost_bps=ctx.config.cost_bps * cost_multiplier)
        res = run(chosen["params"], config, _drag(spec, spread_bps))
        return res.returns, res.benchmarks["buy_and_hold"].returns

    vix = ctx.features["vix"].reindex(ctx.returns.index) if "vix" in ctx.features else None
    return JudgeInputs(
        hypothesis_id=spec.id,
        returns=ctx.result.returns,
        benchmark=ctx.result.benchmarks["buy_and_hold"].returns,
        rf_daily=ctx.rf,
        trial_returns=ledger.trial_matrix(),
        n_trials=ledger.count_trials(),
        held=ctx.result.daily["position"],
        fund_returns=ctx.returns,
        cost_bps=ctx.config.cost_bps,
        params=chosen["params"],
        vix=vix,
        evaluate=evaluate,
        stress_fn=stress_fn,
    )


def judge_hypothesis(hypothesis_id: str, seed: int = JUDGE_SEED) -> dict:
    """Run the full train battery and write ``results/<id>/verdict.json``."""
    ctx = prepare(hypothesis_id)
    verdict = judge(
        judge_inputs(ctx),
        load_thresholds(),
        thresholds_hash(CONFIG_DIR / "thresholds.yaml"),
        seed=seed,
    )
    verdict["chosen_trial"] = ctx.chosen["trial_id"]
    verdict["chosen_params"] = ctx.chosen["params"]
    out = cache.results_dir() / hypothesis_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "verdict.json").write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n")
    return verdict


def _holdout_run(ctx: Context):
    """Build the ``run`` callable for ``score_holdout``: the frozen signal on the hold-out slice.

    Features come from the hold-out slice alone (no splice with train across the embargo), so a
    signal with a lookback is flat until it has enough hold-out history.
    """
    uni = ctx.spec.universe

    def run(frame: pd.DataFrame):
        if uni.research_universe == "real":
            prices = frame[uni.fund]
            rets = daily_returns(prices).dropna()
        else:
            under = daily_returns(frame[uni.underlying]).dropna()
            rets = synthetic_returns(under, frame[cache.fred_name("DFF")], uni.leverage)
            prices = 100 * (1 + rets).cumprod()
            prices = pd.concat([pd.Series([100.0], index=[frame.index[0]]), prices])
        features = pd.DataFrame({"close": prices})
        for column, name in {"underlying": uni.underlying, "vix": "^VIX"}.items():
            if name and name in frame:
                features[column] = frame[name].reindex(features.index)
        rf_col = cache.fred_name(RF_SERIES)
        rf = daily_risk_free(frame[rf_col]).reindex(rets.index)
        if rf.isna().any():
            raise RunError("hold-out risk-free rate has gaps")
        res = run_backtest(ctx.factory(**ctx.chosen["params"]), features, rets, rf, ctx.config)
        return res.returns, res.benchmarks["buy_and_hold"].returns, rf

    return run


def holdout_hypothesis(hypothesis_id: str, seed: int = JUDGE_SEED) -> dict:
    """Score the chosen point once on the hold-out; returns only pass/fail and a timestamp.

    Refuses unless the train verdict is ``advance``. The ledger record and the one-shot refusal
    are Milestone 4 and are not enforced here.
    """
    key = os.environ.get("LAB_HOLDOUT_KEY")
    if not key:
        raise RunError("LAB_HOLDOUT_KEY is not set (human-run command)")
    verdict = judge_hypothesis(hypothesis_id, seed=seed)
    if verdict["train_verdict"] != "advance":
        raise RunError(f"{hypothesis_id}: train verdict is reject; the hold-out is not scored")
    ctx = prepare(hypothesis_id)
    train_excess = cagr(ctx.result.returns) - cagr(ctx.result.benchmarks["buy_and_hold"].returns)
    return score_holdout(
        hypothesis_id,
        _holdout_run(ctx),
        train_excess,
        load_thresholds().holdout,
        key=key,
    )
