"""The ledger is append-only (SPEC Section 7.3): no existing ``trials.jsonl`` line may change."""

import shutil
import subprocess
from pathlib import Path

import pytest

from core.ledger.ledger import LedgerError, verify_append_only

REPO_ROOT = Path(__file__).parents[2]
TRIALS = "ledger/trials.jsonl"


def test_appending_lines_is_allowed():
    verify_append_only('{"n": 1}\n{"n": 2}\n', '{"n": 1}\n{"n": 2}\n{"n": 3}\n')
    verify_append_only("", '{"n": 1}\n')
    verify_append_only("", "")


def test_modifying_an_existing_line_fails():
    with pytest.raises(LedgerError, match="line 2 was modified"):
        verify_append_only('{"n": 1}\n{"n": 2}\n', '{"n": 1}\n{"n": 22}\n{"n": 3}\n')


def test_removing_or_reordering_lines_fails():
    with pytest.raises(LedgerError, match="removed"):
        verify_append_only('{"n": 1}\n{"n": 2}\n', '{"n": 1}\n')
    with pytest.raises(LedgerError):
        verify_append_only('{"n": 1}\n{"n": 2}\n', '{"n": 2}\n{"n": 1}\n')


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True, check=True
    ).stdout


def test_committed_ledger_history_only_ever_appended():
    """Every commit that touched ``ledger/trials.jsonl`` extended the previous version, and the
    working tree extends HEAD. Skipped where there is no git history to walk (a shallow clone)."""
    if shutil.which("git") is None:
        pytest.skip("git not available")
    try:
        if _git("rev-parse", "--is-shallow-repository").strip() == "true":
            pytest.skip("shallow clone: ledger history is not available")
        commits = _git("log", "--reverse", "--format=%H", "--", TRIALS).split()
    except subprocess.CalledProcessError:
        pytest.skip("not a git checkout")
    versions = []
    for commit in commits:
        shown = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "show", f"{commit}:{TRIALS}"],
            capture_output=True,
            text=True,
        )
        versions.append(shown.stdout if shown.returncode == 0 else "")
    working = REPO_ROOT / TRIALS
    if working.exists():
        versions.append(working.read_text())
    for before, after in zip(versions, versions[1:], strict=False):
        verify_append_only(before, after)
