"""Backtest engine (SPEC Sections 5.2 and 5.3).

Asset-agnostic: it sees a signal, a features frame, fund returns and a risk-free rate, nothing
about what the fund is.

Timing. A signal's value on date ``t`` is a target position decided at the close of ``t``. The
engine holds it over the *next* trading day, so ``strategy_return[t+1]`` uses ``position[t]``.
Signal authors have no way to change this lag. Turnover and costs are booked on the day the new
position starts earning (t+1), so the first held day pays for entering from a flat book.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from core.config import load_lab_config
from core.engine.metrics import TRADING_DAYS, compute_metrics
from core.engine.signal_api import (
    POSITION_MAX,
    POSITION_MIN,
    Signal,
    compute_positions,
)

LEAKAGE_K = 25  # truncation dates per signal (captain's decision, M2)
LEAKAGE_SEED = 20260929  # fixed so CI runs are reproducible
LEAKAGE_ATOL = 1e-9  # rolling-window arithmetic differs in the last bits with history length


class LeakageError(AssertionError):
    """A signal's value at a date changed when data after that date was removed."""


class BacktestError(ValueError):
    """Inputs to the engine are inconsistent (misaligned index, missing rates, ...)."""


@dataclass(frozen=True)
class ExecutionConfig:
    """Execution assumptions. Sizing bounds and the turnover cap are off by default."""

    cost_bps: float = 5.0
    min_position: float = POSITION_MIN
    max_position: float = POSITION_MAX
    max_turnover: float | None = None  # max |change in position| per day; None = unlimited

    def __post_init__(self) -> None:
        if self.cost_bps < 0:
            raise ValueError("cost_bps must be non-negative")
        if not POSITION_MIN <= self.min_position <= self.max_position <= POSITION_MAX:
            raise ValueError("need -1 <= min_position <= max_position <= 1")
        if self.max_turnover is not None and self.max_turnover <= 0:
            raise ValueError("max_turnover must be positive when set")

    @classmethod
    def from_lab_config(cls, **overrides) -> ExecutionConfig:
        """Defaults from config/lab.yaml (``cost_bps``); keyword arguments override."""
        return cls(**{"cost_bps": load_lab_config().cost_bps, **overrides})


def daily_risk_free(annual_percent: pd.Series) -> pd.Series:
    """Daily rate from an annual yield in percent (FRED ``DGS3MO``), compounded over 252 days."""
    return (1 + annual_percent / 100) ** (1 / TRADING_DAYS) - 1


def turnover(positions: pd.Series) -> pd.Series:
    """Absolute change in position per day, starting from a flat book."""
    return positions.diff().abs().fillna(positions.abs())


def trading_costs(turn: pd.Series, cost_bps: float) -> pd.Series:
    """Cost as a fraction of NAV: ``cost_bps`` per unit of turnover."""
    return turn * (cost_bps / 1e4)


def apply_position_limits(targets: pd.Series, config: ExecutionConfig) -> pd.Series:
    """Clip targets to the sizing bounds, then cap the day-over-day change at ``max_turnover``."""
    limited = targets.clip(config.min_position, config.max_position)
    if config.max_turnover is None:
        return limited
    out = np.empty(len(limited))
    held = 0.0
    for i, target in enumerate(limited.to_numpy()):
        held += float(np.clip(target - held, -config.max_turnover, config.max_turnover))
        out[i] = held
    return pd.Series(out, index=limited.index, name=limited.name)


def simulate(
    held: pd.Series, fund_returns: pd.Series, rf_daily: pd.Series, cost_bps: float
) -> pd.DataFrame:
    """Daily accounting for positions already lagged onto the days they are held.

    A unit of the fund earns ``fund_returns``; the rest of NAV earns ``rf_daily``. Turnover is
    the change in the *target* position, so weight drift within a day is ignored.
    """
    turn = turnover(held)
    costs = trading_costs(turn, cost_bps)
    gross = held * fund_returns + (1 - held) * rf_daily
    return pd.DataFrame(
        {
            "position": held,
            "turnover": turn,
            "cost": costs,
            "return": gross - costs,
        }
    )


def check_leakage(
    signal: Signal, features: pd.DataFrame, k: int = LEAKAGE_K, seed: int = LEAKAGE_SEED
) -> list[pd.Timestamp]:
    """Recompute ``signal`` on data truncated at ``k`` seeded random dates (SPEC Section 5.2).

    The value at each truncation date must match the full-history value. Raises ``LeakageError``
    naming the first date that does not. Returns the dates checked.
    """
    full = compute_positions(signal, features)
    rng = np.random.default_rng(seed)
    picks = np.sort(rng.choice(len(features), size=min(k, len(features)), replace=False))
    checked = []
    for i in picks:
        date = features.index[i]
        try:
            truncated = compute_positions(signal, features.iloc[: i + 1])
        except Exception as exc:
            raise LeakageError(
                f"{signal.name}: compute() failed when data after {date.date()} was removed "
                f"({exc}); the signal depends on future rows"
            ) from exc
        got, want = truncated.iloc[-1], full.iloc[i]
        if not np.isclose(got, want, rtol=0, atol=LEAKAGE_ATOL):
            raise LeakageError(
                f"{signal.name}: lookahead leakage on {date.date()}: position is {want:g} with "
                f"full history but {got:g} when data after that date is removed"
            )
        checked.append(date)
    return checked


@dataclass(frozen=True)
class RunResult:
    """One strategy's daily series plus its metrics."""

    daily: pd.DataFrame  # columns: position, turnover, cost, return
    metrics: dict

    @property
    def returns(self) -> pd.Series:
        return self.daily["return"]


@dataclass(frozen=True)
class BacktestResult(RunResult):
    benchmarks: dict[str, RunResult] = field(default_factory=dict)
    leakage_dates_checked: int = 0


def _run(held, fund_returns, rf_daily, cost_bps) -> RunResult:
    daily = simulate(held, fund_returns, rf_daily, cost_bps)
    metrics = compute_metrics(daily["return"], rf_daily, in_market=daily["position"] != 0)
    metrics["total_turnover"] = float(daily["turnover"].sum())
    metrics["total_cost"] = float(daily["cost"].sum())
    return RunResult(daily=daily, metrics=metrics)


def run_backtest(
    signal: Signal,
    features: pd.DataFrame,
    fund_returns: pd.Series,
    rf_daily: pd.Series,
    config: ExecutionConfig | None = None,
    *,
    leakage_k: int = LEAKAGE_K,
    leakage_seed: int = LEAKAGE_SEED,
) -> BacktestResult:
    """Backtest ``signal`` with the one-day lag and compute both benchmarks alongside.

    ``features`` is indexed by every date the signal can see (including the day before the first
    return); ``fund_returns`` is the fund's daily return on each held day; ``rf_daily`` is the
    daily risk-free rate. The leakage self-test always runs first and cannot be skipped
    (``leakage_k=0`` is rejected).
    """
    config = config or ExecutionConfig.from_lab_config()
    if leakage_k < 1:
        raise BacktestError("the leakage self-test cannot be disabled (leakage_k >= 1)")
    if not features.index.is_monotonic_increasing or not features.index.is_unique:
        raise BacktestError("features must have a sorted, unique date index")
    if not fund_returns.index.isin(features.index).all():
        raise BacktestError("every return date must also be a features date")
    if fund_returns.isna().any():
        day = fund_returns.index[fund_returns.isna().to_numpy()][0].date()
        raise BacktestError(f"fund return is NaN on {day}; refusing to fill data gaps")
    rf_daily = rf_daily.reindex(fund_returns.index)
    if rf_daily.isna().any():
        day = rf_daily.index[rf_daily.isna().to_numpy()][0].date()
        raise BacktestError(f"risk-free rate is missing on {day}")

    checked = check_leakage(signal, features, leakage_k, leakage_seed)
    targets = apply_position_limits(compute_positions(signal, features), config)
    # The lag: today's target is held over the next session. Reindexing after the shift keeps
    # each held position attached to the return date it earns.
    held = targets.shift(1).fillna(0.0).reindex(fund_returns.index)
    if held.isna().any():
        raise BacktestError("return dates before the first features date have no position")

    def const(weight: float) -> pd.Series:
        return pd.Series(weight, index=fund_returns.index)

    result = _run(held, fund_returns, rf_daily, config.cost_bps)
    benchmarks = {
        "buy_and_hold": _run(const(1.0), fund_returns, rf_daily, config.cost_bps),
        "half_cash": _run(const(0.5), fund_returns, rf_daily, config.cost_bps),
    }
    return BacktestResult(
        daily=result.daily,
        metrics=result.metrics,
        benchmarks=benchmarks,
        leakage_dates_checked=len(checked),
    )
