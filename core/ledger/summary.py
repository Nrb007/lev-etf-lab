"""Aggregate ledger summary for the research-loop agents (SPEC Section 9.1).

Trial counts and the train-split verdict state per hypothesis, and nothing hold-out related: no
hold-out verdict, no hold-out attempt record, nothing read from ``results/holdout/``. The
hypothesis agent is given this summary in its task prompt.
"""

from __future__ import annotations

import json
from collections import Counter

from core.data import cache
from core.ledger import ledger


def train_verdict(hypothesis_id: str) -> dict | None:
    """The train verdict and failing tests of ``results/<id>/verdict.json``, if judged."""
    path = cache.results_dir() / hypothesis_id / "verdict.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return {"train_verdict": data.get("train_verdict"), "reasons": data.get("reasons", [])}


def summarize() -> dict:
    trials = ledger.read_trials()
    per_hypothesis: dict[str, dict] = {}
    for trial in trials:
        entry = per_hypothesis.setdefault(trial["hypothesis_id"], {"trials": 0})
        entry["trials"] += 1
    for hid, entry in per_hypothesis.items():
        verdict = train_verdict(hid)
        entry.update(verdict or {"train_verdict": "not judged", "reasons": []})
    counts = Counter(e["train_verdict"] for e in per_hypothesis.values())
    return {
        "n_trials": len(trials),
        "n_hypotheses": len(per_hypothesis),
        "train_verdict_counts": dict(counts),
        "hypotheses": dict(sorted(per_hypothesis.items())),
    }


def format_summary(summary: dict) -> str:
    lines = [
        f"N = {summary['n_trials']} trials across {summary['n_hypotheses']} hypotheses "
        f"(train verdicts: {summary['train_verdict_counts'] or 'none yet'})"
    ]
    for hid, e in summary["hypotheses"].items():
        failing = f"; failing: {', '.join(e['reasons'])}" if e["reasons"] else ""
        lines.append(f"  {hid}: {e['trials']} trials, {e['train_verdict']}{failing}")
    return "\n".join(lines)
