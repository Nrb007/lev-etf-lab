"""Throwaway git repositories holding pre-registered hypotheses, for the ledger and CLI tests."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import yaml

SIGNAL_FIXTURE = Path(__file__).parent / "fixtures" / "hypotheses" / "h9999_ma_signal.py"
SIGNAL_REL = "hypotheses/signals/h9999_ma_signal.py"


def git(repo: Path, *args: str, date: str | None = None) -> str:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
    if date:
        env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"] = date
    out = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return out.stdout.strip()


def commit_all(repo: Path, message: str = "commit", date: str | None = None) -> str:
    git(repo, "add", "-A")
    git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", message, date=date)
    return git(repo, "rev-parse", "HEAD")


def full_spec(hid: str = "H-9999", params: dict | None = None, **overrides) -> dict:
    spec = {
        "id": hid,
        "title": "test-only moving average",
        "mechanism": "Test-only: a trend filter on a fund that a leaky signal could game.",
        "universe": {"fund": "TQQQ", "underlying": "QQQ", "research_universe": "real"},
        "signal_module": SIGNAL_REL,
        "params": params or {"window": {"values": [5, 10, 20]}},
        "benchmark": "buy_and_hold",
        "primary_metric": "sharpe",
        "registered_at": "2019-01-01",
        "notes_on_prior_trials": "none",
    }
    return {**spec, **overrides}


def init_repo(root: Path) -> Path:
    """An empty repo with the signal fixture committed; specs live in ``root/hypotheses``."""
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", "main")
    (root / SIGNAL_REL).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(SIGNAL_FIXTURE, root / SIGNAL_REL)
    commit_all(root, "signal", date="2019-01-01T00:00:00+00:00")
    return root


def write_spec(repo: Path, hid: str = "H-9999", params=None, commit: bool = True, **overrides):
    path = repo / "hypotheses" / f"{hid}_test.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(full_spec(hid, params, **overrides)))
    if commit:
        commit_all(repo, f"register {hid}", date="2019-01-02T00:00:00+00:00")
    return path
