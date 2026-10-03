"""``lab run``: backtest a hypothesis's parameter grid on the train split (SPEC Section 5.4).

Every grid point is backtested, its return series and one trial line are written to the ledger,
and N goes up by one. Before anything runs, ``core.ledger.prereg`` refuses a spec or signal module
that is not committed, is dated after the run, or no longer matches the ledger's spec hash.

A hypothesis spec follows SPEC Section 7.1 (``core.ledger.spec``). Its ``signal_module`` is a Python
file exposing ``make_signal(**params) -> Signal``. Ledger reads and writes go through
``core.ledger.ledger``; this module only assembles inputs and calls it.
"""

from __future__ import annotations

import importlib.util
import itertools
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from core.config import CONFIG_DIR
from core.data import cache
from core.data.splits import load_prices
from core.data.synthetic import daily_returns, research_prices
from core.engine.backtest import (
    BacktestResult,
    ExecutionConfig,
    check_leakage,
    daily_risk_free,
    run_backtest,
)
from core.engine.signal_api import Signal
from core.ledger import ledger, prereg
from core.ledger.spec import HypothesisSpec, SpecError, parse_spec

REPO_ROOT = Path(__file__).resolve().parent.parent
RF_SERIES = "DGS3MO"


class RunError(RuntimeError):
    """The hypothesis cannot be run (missing spec, bad signal module, missing data)."""


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
        return parse_spec(path.read_text(), path.name)
    except SpecError as exc:
        raise RunError(str(exc)) from exc


def signal_path(spec: HypothesisSpec, base: Path | None = None) -> Path:
    """The spec's signal module (path relative to the repo root, or absolute)."""
    module_path = Path(spec.signal_module)
    if not module_path.is_absolute():
        module_path = (base or hypotheses_dir().parent) / module_path
    if not module_path.exists():
        raise RunError(f"{spec.id}: signal module {module_path} not found")
    return module_path


def _import_factory(spec_id: str, module_path: Path):
    module_spec = importlib.util.spec_from_file_location(f"_signal_{spec_id}", module_path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    factory = getattr(module, "make_signal", None)
    if factory is None:
        raise RunError(f"{module_path.name} must define make_signal(**params) -> Signal")
    return factory


def load_signal_factory(spec: HypothesisSpec, base: Path | None = None):
    """Import the spec's signal module from the working tree."""
    return _import_factory(spec.id, signal_path(spec, base))


def load_signal_factory_from_source(spec: HypothesisSpec, source: bytes):
    """Import a signal module from its committed bytes (the frozen hold-out signal)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / Path(spec.signal_module).name
        path.write_bytes(source)
        return _import_factory(spec.id, path)


def grid_points(spec: HypothesisSpec) -> list[dict]:
    """Cartesian product of the spec's parameter values, in spec order."""
    names = list(spec.params)
    return [
        dict(zip(names, combo, strict=True))
        for combo in itertools.product(*(spec.params[n].values for n in names))
    ]


def build_inputs(spec: HypothesisSpec) -> tuple[pd.DataFrame, pd.Series, pd.Series, dict]:
    """(features, fund returns, daily risk-free, universe metadata), all train split.

    Features are ``close`` (the fund), plus ``underlying`` and ``vix`` when they are cached, plus
    any series the spec lists under ``universe.features`` (required: a missing one is an error). A
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
    for column, name in uni.features.items():
        features[column] = load_prices(name, "train")[name].reindex(features.index)
    rf_name = cache.fred_name(RF_SERIES)
    rf = daily_risk_free(load_prices(rf_name, "train")[rf_name])
    returns = daily_returns(prices).dropna()
    rf = rf.reindex(returns.index)
    if rf.isna().any():
        raise RunError(f"{RF_SERIES} is missing on {rf.index[rf.isna().to_numpy()][0].date()}")
    return features, returns, rf, meta


def run_hypothesis(hypothesis_id: str, config: ExecutionConfig | None = None) -> dict:
    """Backtest every grid point, record it in the ledger, and return a JSON-able summary."""
    spec_path = find_spec(hypothesis_id)
    spec = load_spec(spec_path)
    if spec.id != hypothesis_id:
        raise RunError(f"{spec_path.name} declares id {spec.id}, expected {hypothesis_id}")
    run_at = datetime.now(UTC)
    reg = prereg.verify_registration(
        spec_path,
        signal_path(spec),
        run_at=run_at,
        prior_trials=[t for t in ledger.read_trials() if t["hypothesis_id"] == hypothesis_id],
    )
    factory = load_signal_factory(spec)
    points = grid_points(spec)
    if not points:
        raise RunError(f"{hypothesis_id}: empty parameter grid")
    config = config or ExecutionConfig.from_lab_config()
    features, returns, rf, meta = build_inputs(spec)

    common = {
        "hypothesis_id": hypothesis_id,
        "spec_hash": reg.spec_hash,
        "signal_hash": reg.signal_hash,
        "spec_path": reg.spec_path,
        "signal_path": reg.signal_path,
        "thresholds_hash": prereg.file_hash(CONFIG_DIR / "thresholds.yaml"),
        "git_commit": reg.commit,
        "registered_commit_at": reg.committed_at.isoformat(),
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


def check_leakage_for(hypothesis_id: str, seed: int | None = None) -> dict:
    """Run the engine's leakage self-test on every grid point of a spec (no ledger writes).

    Reads the spec and signal from the working tree, so it works before pre-registration; it is
    what the skeptic runs in its pre-run review. Raises ``LeakageError`` at the first leak.
    """
    spec_path = find_spec(hypothesis_id)
    spec = load_spec(spec_path)
    if spec.id != hypothesis_id:
        raise RunError(f"{spec_path.name} declares id {spec.id}, expected {hypothesis_id}")
    factory = load_signal_factory(spec)
    points = grid_points(spec)
    if not points:
        raise RunError(f"{hypothesis_id}: empty parameter grid")
    features, _, _, _ = build_inputs(spec)
    kwargs = {} if seed is None else {"seed": seed}
    checked = 0
    for params in points:
        checked = len(check_leakage(factory(**params), features, **kwargs))
    return {
        "hypothesis_id": hypothesis_id,
        "grid_points": len(points),
        "dates_checked_per_point": checked,
        "passed": True,
    }
