"""Simulated worlds for the judge validation tests (SPEC Section 6.4).

Throwaway fixtures: a fund whose returns are Gaussian noise plus, optionally, a planted
predictable component, and a family of threshold signals on latent features. No real hypothesis
is involved and nothing touches the ledger; the trial matrix is built in memory.

World: ``r[t+1] = MU + SIGMA * (beta * z[t] + eps[t+1])`` where ``z`` is a unit-variance AR(1)
feature known at the close of ``t`` and ``eps`` is standard normal noise. ``beta = 0`` is pure
noise. A signal "long when smoothed z > threshold" then has a known population Sharpe.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

import numpy as np
import pandas as pd

from core.config import Thresholds, load_thresholds
from core.engine.backtest import simulate
from core.engine.metrics import TRADING_DAYS
from core.judge.common import sharpe
from core.judge.verdict import JudgeInputs, judge, thresholds_hash

MU = 0.0002  # daily drift of the fund, roughly 5% a year
SIGMA = 0.02  # daily volatility, about 32% a year
RF = 0.0001  # daily risk-free rate, about 2.5% a year
PHI = 0.97  # persistence of the feature: regimes last a few weeks
COST_BPS = 5.0
LEVERAGE = 3  # only used to translate a financing spread into a return drag in the stress
N_FEATURES = 10

WINDOWS = [1, 2, 3, 5, 8, 13, 21, 34]
THRESHOLDS_GRID = [-0.6, -0.4, -0.2, 0.0, 0.2, 0.4, 0.6]  # 56 grid points >= min_trials (50)


class ThresholdSignal:
    """Long when the trailing mean of feature ``col`` exceeds ``thr`` (close of day t only)."""

    def __init__(self, col: str = "z0", window: int = 5, thr: float = 0.0):
        self.name = f"thr_{col}_{window}_{thr:g}"
        self.params = {"col": col, "window": window, "thr": thr}

    def compute(self, features: pd.DataFrame) -> pd.Series:
        mean = features[self.params["col"]].rolling(self.params["window"]).mean()
        return (mean > self.params["thr"]).astype("float64").where(mean.notna())


@dataclass(frozen=True)
class World:
    features: pd.DataFrame  # z0..z9 and vix, indexed by date
    fund: pd.Series  # daily fund returns (first date has no return: index[1:])
    rf: pd.Series


def _ar1(rng: np.random.Generator, n: int, size: int) -> np.ndarray:
    eps = rng.standard_normal((n, size)) * np.sqrt(1 - PHI**2)
    out = np.empty((n, size))
    out[0] = rng.standard_normal(size)
    for i in range(1, n):
        out[i] = PHI * out[i - 1] + eps[i]
    return out


def make_world(seed: int, t: int, beta: float = 0.0) -> World:
    """``t`` return days. Feature 0 is the planted one when ``beta`` is non-zero."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2010-01-04", periods=t + 1)
    z = _ar1(rng, t + 1, N_FEATURES)
    eps = rng.standard_normal(t + 1)
    ret = np.empty(t + 1)
    ret[0] = np.nan
    ret[1:] = MU + SIGMA * (beta * z[:-1, 0] + eps[1:])
    vix = np.exp(3.0 + 0.3 * _ar1(rng, t + 1, 1)[:, 0])  # independent of returns
    features = pd.DataFrame(z, index=dates, columns=[f"z{i}" for i in range(N_FEATURES)])
    features["vix"] = vix
    fund = pd.Series(ret, index=dates).iloc[1:]
    return World(features, fund, pd.Series(RF, index=fund.index))


def held_positions(signal: ThresholdSignal, world: World) -> pd.Series:
    targets = signal.compute(world.features).fillna(0.0)
    return targets.shift(1).fillna(0.0).reindex(world.fund.index)


def strategy_returns(
    params: dict, world: World, *, cost_mult: float = 1.0, fund_drag: float = 0.0
) -> pd.Series:
    held = held_positions(ThresholdSignal(**params), world)
    fund = world.fund - fund_drag
    return simulate(held, fund, world.rf, COST_BPS * cost_mult)["return"]


def benchmark_returns(world: World, *, cost_mult: float = 1.0, fund_drag: float = 0.0) -> pd.Series:
    held = pd.Series(1.0, index=world.fund.index)
    return simulate(held, world.fund - fund_drag, world.rf, COST_BPS * cost_mult)["return"]


def grid_params() -> list[dict]:
    return [{"col": "z0", "window": w, "thr": thr} for w in WINDOWS for thr in THRESHOLDS_GRID]


def random_params(rng: np.random.Generator, n: int) -> list[dict]:
    """Random-parameter variants across all features (used to snoop for a lucky winner)."""
    return [
        {
            "col": f"z{int(rng.integers(0, N_FEATURES))}",
            "window": int(rng.integers(1, 61)),
            "thr": round(float(rng.uniform(-1.0, 1.0)), 3),
        }
        for _ in range(n)
    ]


def judge_world(
    world: World,
    trial_params: list[dict],
    *,
    seed: int = 1,
    thresholds: Thresholds | None = None,
    thresholds_sha256: str | None = None,
) -> dict:
    """Backtest every trial, take the best in-sample by Sharpe, and run the full judge on it."""
    thresholds = thresholds or load_thresholds()
    trials = {i: strategy_returns(p, world) for i, p in enumerate(trial_params)}
    matrix = pd.DataFrame(trials)
    sharpes = (matrix.sub(world.rf, axis=0)).apply(sharpe)
    best = int(sharpes.idxmax())
    params = trial_params[best]
    spread = 200 / 1e4 / TRADING_DAYS * (LEVERAGE - 1)

    def stress_fn(cost_mult: float, spread_bps: float):
        drag = spread_bps / 1e4 / TRADING_DAYS * (LEVERAGE - 1)
        return (
            strategy_returns(params, world, cost_mult=cost_mult, fund_drag=drag),
            benchmark_returns(world, cost_mult=cost_mult, fund_drag=drag),
        )

    del spread
    inputs = JudgeInputs(
        hypothesis_id="H-SIM",
        returns=matrix[best],
        benchmark=benchmark_returns(world),
        rf_daily=world.rf,
        trial_returns=matrix,
        n_trials=len(trial_params),
        held=held_positions(ThresholdSignal(**params), world),
        fund_returns=world.fund,
        cost_bps=COST_BPS,
        params=params,
        vix=world.features["vix"].reindex(world.fund.index),
        evaluate=lambda p: strategy_returns(p, world),
        stress_fn=stress_fn,
    )
    return judge(inputs, thresholds, thresholds_sha256 or thresholds_hash(), seed=seed)


@cache
def population_sharpe(beta: float) -> float:
    """Annualized Sharpe (excess of cash, after costs) of 'long when z > 0' in the planted world.

    Estimated once on a long simulated sample; this is the edge size the power table is
    indexed by.
    """
    world = make_world(seed=987654321, t=200_000, beta=beta)
    ret = strategy_returns({"col": "z0", "window": 1, "thr": 0.0}, world)
    return float(sharpe(ret - world.rf))
