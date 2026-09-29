"""Pydantic models and loaders for config/lab.yaml and config/thresholds.yaml."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LeveragedFund(_Strict):
    ticker: str
    leverage: int


class RateSeries(_Strict):
    source: Literal["FRED"]
    series: str


class Universe(_Strict):
    underlyings: list[str]
    leveraged_3x: list[str]
    loaded_not_used: list[LeveragedFund]
    volatility: list[str]
    rates: list[RateSeries]


class LabConfig(_Strict):
    universe: Universe
    holdout_start: date
    embargo_trading_days: int = Field(ge=0)
    cost_bps: float = Field(ge=0)


class Dsr(_Strict):
    min_probability: float = Field(gt=0, le=1)


class Spa(_Strict):
    max_p_value: float = Field(gt=0, le=1)


class Pbo(_Strict):
    max_pbo: float = Field(gt=0, le=1)
    cscv_partitions: int = Field(gt=0)
    min_trials: int = Field(gt=0)


class Permutation(_Strict):
    max_p_value: float = Field(gt=0, le=1)
    min_shifts: int = Field(gt=0)


class Sensitivity(_Strict):
    perturbations: list[float]
    min_median_neighbor_sharpe_ratio: float
    min_fraction_neighbors_beating_benchmark: float = Field(ge=0, le=1)


class Stress(_Strict):
    cost_multiplier: float = Field(gt=0)
    financing_spread_bps: float
    min_excess_sharpe: float


class Regime(_Strict):
    min_fraction_positive_regimes: float = Field(ge=0, le=1)
    max_single_regime_share: float = Field(ge=0, le=1)


class Holdout(_Strict):
    min_excess_return: float
    min_excess_sharpe: float


class Thresholds(_Strict):
    dsr: Dsr
    spa: Spa
    pbo: Pbo
    permutation: Permutation
    sensitivity: Sensitivity
    stress: Stress
    regime: Regime
    holdout: Holdout


def _load(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f)


def load_lab_config(path: Path = CONFIG_DIR / "lab.yaml") -> LabConfig:
    return LabConfig.model_validate(_load(path))


def load_thresholds(path: Path = CONFIG_DIR / "thresholds.yaml") -> Thresholds:
    return Thresholds.model_validate(_load(path))
