"""Dashboard data export (SPEC Section 11): every number the dashboard shows comes from here.

``lab dashboard export`` turns the ledger, the specs and the judge's ``verdict.json`` files into
the JSON the static site reads, so no figure on the site is computed or typed by hand:

* ``results/<id>/detail.json``: mechanism, chosen point, equity and drawdown curves against the
  benchmarks (recomputed by the engine from the spec and the ledger, and required to match the
  ledger's returns), the parameter grid's Sharpe ratios for the heatmap, and the test battery.
* ``results/index.json``: one row per hypothesis (verdict, failing tests, skeptic recommendations,
  hold-out status), the funnel counts and the trial count N.

Hold-out: only pass/fail and the date scored, taken from the attempt record
``ledger/holdout_attempts.jsonl`` (which stores only that word, never a metric). The file with the
full hold-out metrics is never read here, so the dashboard cannot show more than that.

Curves are sampled every ``SAMPLE_EVERY`` sessions (plus the last) to keep the site small;
drawdown keeps the worst value in each block so the trough is never smoothed away.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from core.data import cache
from core.engine.metrics import TRADING_DAYS, equity_curve
from core.judge_runner import prepare
from core.ledger import ledger
from core.runner import RunError, find_spec, load_spec

SAMPLE_EVERY = 5
SCHEMA_VERSION = 1
FUNNEL_STAGES = ["proposed", "passed_skeptic", "passed_judge", "passed_holdout"]
_REC = re.compile(r"^\s*\**Recommendation \((pre|post)-run\):\s*\**\s*(clear|block)\b", re.I | re.M)


def _write_json(path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, sort_keys=True, allow_nan=False) + "\n")


def _clean(value):
    """Replace NaN/inf (undefined metrics) with None so the JSON is strict."""
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, np.generic):
        return _clean(value.item())
    return value


def _sample(index: pd.DatetimeIndex) -> np.ndarray:
    positions = np.arange(0, len(index), SAMPLE_EVERY)
    if positions[-1] != len(index) - 1:
        positions = np.append(positions, len(index) - 1)
    return positions


def curves(strategy: pd.Series, benchmarks: dict[str, pd.Series]) -> list[dict]:
    """Equity (start = 1) and drawdown rows, sampled; drawdown is the block minimum."""
    frame = {"strategy": strategy, **benchmarks}
    equity = {name: equity_curve(ret) for name, ret in frame.items()}
    drawdown = {name: eq / np.maximum.accumulate(eq) - 1 for name, eq in equity.items()}
    positions = _sample(strategy.index)
    rows = []
    for k, pos in enumerate(positions):
        start = positions[k - 1] + 1 if k else 0
        row = {"date": str(strategy.index[pos].date())}
        for name in frame:
            row[f"equity_{name}"] = float(equity[name].iloc[pos])
            row[f"drawdown_{name}"] = float(drawdown[name].iloc[start : pos + 1].min())
        rows.append(row)
    return rows


def _holdout_status(hypothesis_id: str) -> dict | None:
    """Pass/fail and date scored from the attempt record; ``None`` if not (yet) scored."""
    finished = [
        e
        for e in ledger.read_holdout_attempts()
        if e["hypothesis_id"] == hypothesis_id and e["event"] == "finished"
    ]
    if not finished:
        return None
    last = finished[-1]
    return {"verdict": last["outcome"], "scored_on": last["timestamp"][:10]}


def review_recommendations(hypothesis_id: str) -> dict:
    """The skeptic's last pre-run and post-run recommendation in ``review.md`` (or ``None``)."""
    path = cache.results_dir() / hypothesis_id / "review.md"
    found: dict[str, str | None] = {"pre": None, "post": None}
    if path.exists():
        for phase, verdict in _REC.findall(path.read_text()):
            found[phase.lower()] = verdict.lower()
    return found


def _read_text(path) -> str | None:
    return path.read_text() if path.exists() else None


def export_hypothesis(hypothesis_id: str) -> dict:
    """Write ``results/<id>/detail.json`` for a judged hypothesis and return it."""
    out = cache.results_dir() / hypothesis_id
    verdict_path = out / "verdict.json"
    if not verdict_path.exists():
        raise RunError(f"{hypothesis_id} has no verdict.json; run `lab judge` first")
    verdict = json.loads(verdict_path.read_text())
    ctx = prepare(hypothesis_id)
    spec = ctx.spec
    trials = [t for t in ledger.read_trials() if t["hypothesis_id"] == hypothesis_id]
    bench = ctx.result.benchmarks
    detail = {
        "schema_version": SCHEMA_VERSION,
        "id": spec.id,
        "title": spec.title,
        "mechanism": " ".join(spec.mechanism.split()),
        "notes_on_prior_trials": " ".join(spec.notes_on_prior_trials.split()),
        "registered_at": str(spec.registered_at),
        "universe": spec.universe.model_dump(),
        "param_names": list(spec.params),
        "param_values": {k: v.values for k, v in spec.params.items()},
        "chosen_params": ctx.chosen["params"],
        "chosen_trial": ctx.chosen["trial_id"],
        "window": ctx.chosen["window"],
        "n_trials_hypothesis": len(trials),
        "metrics": {
            "strategy": ctx.result.metrics,
            "buy_and_hold": bench["buy_and_hold"].metrics,
            "half_cash": bench["half_cash"].metrics,
        },
        "curves": curves(
            ctx.result.returns,
            {name: run.returns for name, run in bench.items()},
        ),
        "grid": [
            {"params": t["params"], "sharpe": t["metrics"].get("sharpe"), "trial": t["trial_id"]}
            for t in trials
        ],
        "verdict": verdict,
        "reviews": review_recommendations(hypothesis_id),
        "review_md": _read_text(out / "review.md"),
        "report_md": _read_text(out / "report.md"),
        "holdout": _holdout_status(hypothesis_id),
    }
    detail = _clean(detail)
    _write_json(out / "detail.json", detail)
    return detail


def _hypothesis_ids() -> list[str]:
    return sorted({t["hypothesis_id"] for t in ledger.read_trials()})


def export_index(ids: list[str] | None = None) -> dict:
    """Write ``results/index.json``: rows, funnel and N for every hypothesis in the ledger.

    Only ``results/<id>/`` for ledger ids is read or written; ``results/demo/`` (the committed
    simulated demo) is never touched.
    """
    ids = ids if ids is not None else _hypothesis_ids()
    rows = []
    detail: dict = {}
    for hid in ids:
        detail_path = cache.results_dir() / hid / "detail.json"
        if not detail_path.exists():
            continue
        detail = json.loads(detail_path.read_text())
        v = detail["verdict"]
        rows.append(
            {
                "id": hid,
                "title": detail["title"],
                "train_verdict": v["train_verdict"],
                "reasons": v["reasons"],
                "holdout": detail["holdout"],
                "skeptic_pre": detail["reviews"]["pre"],
                "skeptic_post": detail["reviews"]["post"],
                "trials": detail["n_trials_hypothesis"],
                "sharpe": detail["metrics"]["strategy"].get("sharpe"),
                "benchmark_sharpe": detail["metrics"]["buy_and_hold"].get("sharpe"),
                "cagr": detail["metrics"]["strategy"].get("cagr"),
                "max_drawdown": detail["metrics"]["strategy"].get("max_drawdown"),
            }
        )
    holdout_passed = [r for r in rows if r["holdout"] and r["holdout"]["verdict"] == "pass"]
    funnel = {
        "proposed": len(rows),
        "passed_skeptic": sum(r["skeptic_pre"] == "clear" for r in rows),
        "passed_judge": sum(r["train_verdict"] == "advance" for r in rows),
        "passed_holdout": len(holdout_passed),
    }
    thresholds_hashes = sorted({find_verdict_hash(r["id"]) for r in rows})
    index = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "n_trials": ledger.count_trials(),
        "funnel": funnel,
        "data_source": _data_source(detail) if rows else None,
        "expected_max_sharpe_annual": _expected_max_sharpe([r["id"] for r in rows]),
        "thresholds_hash": thresholds_hashes,
        "hypotheses": rows,
    }
    _write_json(cache.results_dir() / "index.json", _clean(index))
    return index


def find_verdict_hash(hypothesis_id: str) -> str:
    return _verdict(hypothesis_id).get("thresholds_hash", "unknown")


def _verdict(hypothesis_id: str) -> dict:
    return json.loads((cache.results_dir() / hypothesis_id / "verdict.json").read_text())


def _data_source(detail: dict) -> dict | None:
    """Where the prices came from, from the cache sidecar (``simulated`` flags a demo universe)."""
    uni = detail["universe"]
    name = uni["fund"] if uni["research_universe"] == "real" else uni["underlying"]
    directory = cache.cache_dir()
    if not name or not cache.has_series(directory, name):
        return None
    meta = cache.read_meta(directory, name)
    return {"source": meta.get("source"), "simulated": bool(meta.get("simulated", False))}


def _expected_max_sharpe(ids: list[str]) -> float | None:
    """Annualised Sharpe the judge expects the best of N noise trials to show (DSR's SR0)."""
    verdicts = [_verdict(hid) for hid in ids]
    if not verdicts:
        return None
    latest = max(verdicts, key=lambda v: v["n_trials"])
    per_period = latest["tests"]["dsr"]["details"].get("expected_max_sharpe_per_period")
    return None if per_period is None else float(per_period) * float(np.sqrt(TRADING_DAYS))


def export_all() -> dict:
    """Export every judged hypothesis in the ledger, then the index."""
    ids = []
    for hid in _hypothesis_ids():
        try:
            find_spec(hid)
            load_spec(find_spec(hid))
        except RunError:
            continue
        if (cache.results_dir() / hid / "verdict.json").exists():
            export_hypothesis(hid)
            ids.append(hid)
    return export_index(ids)
