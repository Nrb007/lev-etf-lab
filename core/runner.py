"""``lab run``: backtest a hypothesis's parameter grid on the train split (SPEC Section 5.4).

Every grid point is backtested, its return series and one trial line are written to the ledger,
and N goes up by one. Pre-registration checks (committed spec, hash, commit date) are Milestone 4
and not enforced here.

A hypothesis spec follows SPEC Section 7.1. Its ``signal_module`` is a Python file exposing
``make_signal(**params) -> Signal``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import itertools
import os
import subprocess
from pathlib import Path
from typing import Literal

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field

from core.config import CONFIG_DIR
from core.data import cache
from core.data.splits import load_prices
from core.data.synthetic import daily_returns, research_prices
from core.engine.backtest import BacktestResult, ExecutionConfig, daily_risk_free, run_backtest
from core.engine.signal_api import Signal
from core.ledger import ledger

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RF_SERIES = "DGS3MO"


class RunError(RuntimeError):
    """The hypothesis cannot be run (missing spec, bad signal module, missing data)."""


class _Loose(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class ParamGrid(_Loose):
    values: list


class Universe(_Loose):
    fund: str
    underlying: str | None = None
    research_universe: Literal["real", "synthetic_long"] = "real"
    leverage: float = 3


class HypothesisSpec(_Loose):
    """The fields the runner needs from SPEC Section 7.1; strict validation is Milestone 4."""

    id: str = Field(pattern=r"^H-\d{4}$")
    universe: Universe
    signal_module: str
    params: dict[str, ParamGrid] = {}


def hypotheses_dir() -> Path:
    return Path(os.environ.get("LAB_HYPOTHESES_DIR") or REPO_ROOT / "hypotheses")


def find_spec(hypothesis_id: str) -> Path:
    matches = sorted(hypotheses_dir().glob(f"{hypothesis_id}_*.yaml"))
    matches += [p for p in [hypotheses_dir() / f"{hypothesis_id}.yaml"] if p.exists()]
    if not matches:
        raise RunError(f"no spec file for {hypothesis_id} in {hypotheses_dir()}")
    if len(matches) > 1:
        raise RunError(f"{hypothesis_id}: several spec files match: {[m.name for m in matches]}")
    return matches[0]


def load_spec(path: Path) -> HypothesisSpec:
    try:
        return HypothesisSpec.model_validate(yaml.safe_load(path.read_text()))
    except (ValueError, yaml.YAMLError) as exc:
        raise RunError(f"{path.name}: invalid spec: {exc}") from exc


def load_signal_factory(spec: HypothesisSpec, base: Path | None = None):
    """Import the spec's signal module (path relative to the repo root, or absolute)."""
    module_path = Path(spec.signal_module)
    if not module_path.is_absolute():
        module_path = (base or hypotheses_dir().parent) / module_path
    if not module_path.exists():
        raise RunError(f"{spec.id}: signal module {module_path} not found")
    module_spec = importlib.util.spec_from_file_location(f"_signal_{spec.id}", module_path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    factory = getattr(module, "make_signal", None)
    if factory is None:
        raise RunError(f"{module_path.name} must define make_signal(**params) -> Signal")
    return factory


def grid_points(spec: HypothesisSpec) -> list[dict]:
    """Cartesian product of the spec's parameter values, in spec order."""
    names = list(spec.params)
    return [
        dict(zip(names, combo, strict=True))
        for combo in itertools.product(*(spec.params[n].values for n in names))
    ]


def build_inputs(spec: HypothesisSpec) -> tuple[pd.DataFrame, pd.Series, pd.Series, dict]:
    """(features, fund returns, daily risk-free, universe metadata), all train split.

    Features are ``close`` (the fund), plus ``underlying`` and ``vix`` when they are cached. A
    date is a return date only if the fund and the risk-free rate both have a value; nothing is
    filled.
    """
    uni = spec.universe
    prices, meta = research_prices(
        uni.fund,
        uni.research_universe,
        leverage=uni.leverage,
        underlying=uni.underlying,
    )
    features = pd.DataFrame({"close": prices})
    extras = {"underlying": uni.underlying, "vix": "^VIX"}
    directory = cache.cache_dir()
    for column, name in extras.items():
        if name and cache.has_series(directory, name):
            features[column] = load_prices(name, "train")[name].reindex(features.index)
    rf_name = cache.fred_name(RF_SERIES)
    rf = daily_risk_free(load_prices(rf_name, "train")[rf_name])
    returns = daily_returns(prices).dropna()
    rf = rf.reindex(returns.index)
    if rf.isna().any():
        raise RunError(f"{RF_SERIES} is missing on {rf.index[rf.isna().to_numpy()][0].date()}")
    return features, returns, rf, meta


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO_ROOT, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_hypothesis(hypothesis_id: str, config: ExecutionConfig | None = None) -> dict:
    """Backtest every grid point, record it in the ledger, and return a JSON-able summary."""
    spec_path = find_spec(hypothesis_id)
    spec = load_spec(spec_path)
    if spec.id != hypothesis_id:
        raise RunError(f"{spec_path.name} declares id {spec.id}, expected {hypothesis_id}")
    factory = load_signal_factory(spec)
    points = grid_points(spec)
    if not points:
        raise RunError(f"{hypothesis_id}: empty parameter grid")
    config = config or ExecutionConfig.from_lab_config()
    features, returns, rf, meta = build_inputs(spec)

    common = {
        "hypothesis_id": hypothesis_id,
        "spec_hash": _file_hash(spec_path),
        "thresholds_hash": _file_hash(CONFIG_DIR / "thresholds.yaml"),
        "git_commit": _git_commit(),
        "universe": meta,
        "execution": {
            "cost_bps": config.cost_bps,
            "min_position": config.min_position,
            "max_position": config.max_position,
            "max_turnover": config.max_turnover,
        },
        "split": "train",
        "window": [str(returns.index[0].date()), str(returns.index[-1].date())],
    }
    trials, benchmarks = [], {}
    for params in points:
        signal: Signal = factory(**params)
        result: BacktestResult = run_backtest(signal, features, returns, rf, config)
        stored = ledger.append_trial(
            {**common, "params": params, "metrics": result.metrics}, result.returns
        )
        trials.append(stored)
        benchmarks = {name: b.metrics for name, b in result.benchmarks.items()}
    return {
        "hypothesis_id": hypothesis_id,
        "n_grid_points": len(trials),
        "n_trials_total": ledger.count_trials(),
        "benchmarks": benchmarks,
        "trials": [
            {k: t[k] for k in ("trial_id", "n", "params", "metrics", "returns_path")}
            for t in trials
        ],
    }
