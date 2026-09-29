"""Append-only trial log (SPEC Section 7.3).

One JSON line per backtested grid point in ``ledger/trials.jsonl`` and one parquet of its daily
returns in ``ledger/returns/``. The line count is N, the trial count the multiple-testing
corrections use. Pre-registration checks (``prereg.py``) are Milestone 4 and not enforced here.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def ledger_dir() -> Path:
    return Path(os.environ.get("LAB_LEDGER_DIR") or REPO_ROOT / "ledger")


def trials_path() -> Path:
    return ledger_dir() / "trials.jsonl"


def returns_dir() -> Path:
    return ledger_dir() / "returns"


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

    The parquet lands first so a line never points at a missing file. Returns the stored record.
    """
    n = count_trials() + 1
    trial_id = f"{record['hypothesis_id']}-{n:06d}"
    rel_path = f"returns/{trial_id}.parquet"
    returns_dir().mkdir(parents=True, exist_ok=True)
    returns.rename("return").to_frame().to_parquet(ledger_dir() / rel_path)
    stored = {
        "trial_id": trial_id,
        "n": n,
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        **_jsonable(record),
        "returns_path": rel_path,
    }
    with trials_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(stored, sort_keys=True, allow_nan=False) + "\n")
    return stored


def trial_matrix() -> pd.DataFrame:
    """All trials' return series, one column per trial id, aligned on date (NaN where absent)."""
    columns = {
        t["trial_id"]: pd.read_parquet(ledger_dir() / t["returns_path"])["return"]
        for t in read_trials()
    }
    return pd.DataFrame(columns).sort_index()
