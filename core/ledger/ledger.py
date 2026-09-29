"""Append-only trial log and hold-out attempt log (SPEC Sections 6.3 and 7.3).

One JSON line per backtested grid point in ``ledger/trials.jsonl`` and one parquet of its daily
returns in ``ledger/returns/``. The line count is N, the trial count the multiple-testing
corrections use. This module is the only place the ledger is read or written; ``core/runner.py``
and ``core/judge_runner.py`` call into it. Pre-registration checks live in ``prereg.py``.

``ledger/holdout_attempts.jsonl`` holds one attempt per hypothesis (``reserve_holdout_attempt``).
"""

from __future__ import annotations

import fcntl
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class LedgerError(RuntimeError):
    """A ledger rule was violated (pre-registration, one-shot hold-out, append-only)."""


class HoldoutAlreadyScoredError(LedgerError):
    """The hypothesis already has a hold-out attempt on record (SPEC Section 6.3)."""


def ledger_dir() -> Path:
    return Path(os.environ.get("LAB_LEDGER_DIR") or REPO_ROOT / "ledger")


def trials_path() -> Path:
    return ledger_dir() / "trials.jsonl"


def returns_dir() -> Path:
    return ledger_dir() / "returns"


def holdout_attempts_path() -> Path:
    return ledger_dir() / "holdout_attempts.jsonl"


def _jsonable(value):
    """Non-finite floats (a Sharpe on zero volatility) become null: JSON has no NaN."""
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, float | np.floating):
        return float(value) if np.isfinite(value) else None
    return value


def read_trials() -> list[dict]:
    path = trials_path()
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def count_trials() -> int:
    """N: every grid point ever recorded, across all hypotheses."""
    return len(read_trials())


def append_trial(record: dict, returns: pd.Series) -> dict:
    """Write ``returns`` to parquet, then append ``record`` (plus bookkeeping) as one line.

    An exclusive lock on ``trials.jsonl`` spans the count, the parquet write and the append, so
    concurrent runs get distinct, gap-free trial numbers. The parquet lands first so a line never
    points at a missing file. Returns the stored record.
    """
    returns_dir().mkdir(parents=True, exist_ok=True)
    with trials_path().open("a+b") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.seek(0)
            n = sum(1 for line in f if line.strip()) + 1
            trial_id = f"{record['hypothesis_id']}-{n:06d}"
            rel_path = f"returns/{trial_id}.parquet"
            returns.rename("return").to_frame().to_parquet(ledger_dir() / rel_path)
            stored = {
                "trial_id": trial_id,
                "n": n,
                "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
                **_jsonable(record),
                "returns_path": rel_path,
            }
            f.seek(0, os.SEEK_END)
            f.write((json.dumps(stored, sort_keys=True, allow_nan=False) + "\n").encode())
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    return stored


def trial_matrix() -> pd.DataFrame:
    """All trials' return series, one column per trial id, aligned on date (NaN where absent)."""
    columns = {
        t["trial_id"]: pd.read_parquet(ledger_dir() / t["returns_path"])["return"]
        for t in read_trials()
    }
    return pd.DataFrame(columns).sort_index()


def verify_append_only(before: str, after: str) -> None:
    """Raise ``LedgerError`` unless ``after`` is ``before`` with lines only added at the end."""
    old = [line for line in before.splitlines() if line.strip()]
    new = [line for line in after.splitlines() if line.strip()]
    if new[: len(old)] != old:
        changed = next((i + 1 for i, (a, b) in enumerate(zip(old, new, strict=False)) if a != b), 0)
        where = f"line {changed} was modified" if changed else "lines were removed"
        raise LedgerError(f"ledger is not append-only: {where}")


def read_holdout_attempts() -> list[dict]:
    path = holdout_attempts_path()
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def holdout_attempted(hypothesis_id: str) -> bool:
    """True once any hold-out event (started, result or error) exists for the hypothesis."""
    return any(e["hypothesis_id"] == hypothesis_id for e in read_holdout_attempts())


def _append_holdout_event(event: dict, *, once: bool) -> dict:
    """Append one line under an exclusive lock; with ``once`` refuse if the id already has any."""
    ledger_dir().mkdir(parents=True, exist_ok=True)
    stored = {"timestamp": datetime.now(UTC).isoformat(timespec="seconds"), **_jsonable(event)}
    with holdout_attempts_path().open("a+b") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            if once:
                f.seek(0)
                for line in f:
                    if line.strip() and json.loads(line)["hypothesis_id"] == event["hypothesis_id"]:
                        raise HoldoutAlreadyScoredError(
                            f"{event['hypothesis_id']} has already been scored on the hold-out; "
                            "each hypothesis gets one attempt"
                        )
            f.seek(0, os.SEEK_END)
            f.write((json.dumps(stored, sort_keys=True, allow_nan=False) + "\n").encode())
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    return stored


def reserve_holdout_attempt(record: dict) -> dict:
    """Consume the hypothesis's one hold-out attempt (event ``started``), or refuse.

    Written before any hold-out number is computed, so a crash mid-scoring still leaves the
    attempt used. The check and the append share one lock, so concurrent callers cannot both win.
    """
    return _append_holdout_event({**record, "event": "started"}, once=True)


def record_holdout_outcome(hypothesis_id: str, outcome: str) -> dict:
    """Close an attempt with ``pass``, ``fail`` or ``error``. Only the pass/fail word is stored."""
    return _append_holdout_event(
        {"hypothesis_id": hypothesis_id, "event": "finished", "outcome": outcome}, once=False
    )
