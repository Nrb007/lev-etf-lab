"""Pre-registration: spec hashing and git-commit verification (SPEC Section 7.2).

``verify_registration`` is the gate ``lab run`` passes through. ``read_at_commit`` and
``verify_frozen`` let ``lab holdout`` load the spec and signal exactly as they were committed,
not as the working tree happens to look today.

The pre-registration commit of a hypothesis is the latest commit that touched its spec file or its
signal module. Both files must be single tracked files in the same git repository.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.ledger.ledger import LedgerError


class PreregError(LedgerError):
    """The hypothesis is not pre-registered as SPEC Section 7.2 requires."""


@dataclass(frozen=True)
class Registration:
    repo: Path
    spec_path: str  # repo-relative, posix
    signal_path: str
    spec_hash: str
    signal_hash: str
    commit: str  # the pre-registration commit
    committed_at: datetime  # committer date of that commit


def bytes_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_hash(path: Path) -> str:
    return bytes_hash(path.read_bytes())


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, check=check
        )
    except OSError as exc:
        raise PreregError(f"git is not available: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        raise PreregError(f"git {' '.join(args)} failed: {exc.stderr.strip()}") from exc


def repo_root(path: Path) -> Path:
    """The git work tree containing ``path`` (a file or directory)."""
    start = path if path.is_dir() else path.parent
    out = _git(start, "rev-parse", "--show-toplevel", check=False)
    if out.returncode != 0:
        raise PreregError(f"{path} is not inside a git repository, so it cannot be pre-registered")
    return Path(out.stdout.strip()).resolve()


def _relative(repo: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo).as_posix()
    except ValueError:
        raise PreregError(f"{path} is outside the git repository {repo}") from None


def verify_registration(
    spec_file: Path,
    signal_file: Path,
    *,
    run_at: datetime,
    prior_trials: list[dict],
) -> Registration:
    """Refuse unless all three SPEC Section 7.2 conditions hold; otherwise describe the commit.

    1. Spec and signal are tracked and have no uncommitted changes (staged or not).
    2. The commit date of the latest commit touching either file is before ``run_at``.
    3. Every prior trial of this hypothesis in the ledger recorded the same spec hash (and the same
       signal hash, when it recorded one) as the files on disk now.
    """
    repo = repo_root(spec_file)
    if repo_root(signal_file) != repo:
        raise PreregError(f"{spec_file.name} and {signal_file.name} are in different repositories")
    rels = [_relative(repo, spec_file), _relative(repo, signal_file)]

    for rel in rels:
        if _git(repo, "ls-files", "--error-unmatch", "--", rel, check=False).returncode != 0:
            raise PreregError(f"{rel} is not committed (untracked or ignored by git)")
    dirty = _git(repo, "status", "--porcelain", "--untracked-files=all", "--", *rels).stdout
    if dirty.strip():
        raise PreregError(f"uncommitted changes to the spec or signal module:\n{dirty.rstrip()}")

    commit = _git(repo, "log", "-1", "--format=%H", "--", *rels).stdout.strip()
    if not commit:
        raise PreregError(f"{rels[0]} and {rels[1]} have no commit yet")
    committed_at = datetime.fromisoformat(
        _git(repo, "log", "-1", "--format=%cI", commit).stdout.strip()
    )
    if committed_at >= run_at:
        raise PreregError(
            f"pre-registration commit {commit[:12]} is dated {committed_at.isoformat()}, "
            f"which is not before the run time {run_at.isoformat()}"
        )

    spec_hash, signal_hash = file_hash(spec_file), file_hash(signal_file)
    for trial in prior_trials:
        if trial["spec_hash"] != spec_hash:
            raise PreregError(
                f"spec hash {spec_hash[:12]} does not match {trial['trial_id']} in the ledger "
                f"({trial['spec_hash'][:12]}): the spec changed after trials were recorded; "
                "register a new hypothesis instead"
            )
        if trial.get("signal_hash") not in (None, signal_hash):
            raise PreregError(
                f"signal module hash {signal_hash[:12]} does not match {trial['trial_id']} in the "
                f"ledger ({trial['signal_hash'][:12]}): the signal changed after trials were "
                "recorded; register a new hypothesis instead"
            )
    return Registration(repo, rels[0], rels[1], spec_hash, signal_hash, commit, committed_at)


def read_at_commit(repo: Path, commit: str, rel_path: str) -> bytes:
    """The bytes of ``rel_path`` as stored in ``commit``."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "show", f"{commit}:{rel_path}"],
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PreregError(f"cannot read {rel_path} at commit {commit}: {exc}") from exc
    return out.stdout


def verify_frozen(repo: Path, trial: dict) -> tuple[bytes, bytes]:
    """(spec bytes, signal bytes) from the trial's pre-registration commit, hash-checked.

    Refuses a trial recorded without a commit and paths (recorded before Milestone 4) and any file
    whose committed content does not hash to what the ledger recorded at run time.
    """
    needed = ("git_commit", "spec_path", "signal_path", "spec_hash", "signal_hash")
    missing = [k for k in needed if not trial.get(k)]
    if missing:
        raise PreregError(
            f"{trial['trial_id']} lacks pre-registration fields {missing}; it cannot be frozen"
        )
    frozen = []
    for path_key, hash_key in (("spec_path", "spec_hash"), ("signal_path", "signal_hash")):
        data = read_at_commit(repo, trial["git_commit"], trial[path_key])
        if bytes_hash(data) != trial[hash_key]:
            raise PreregError(
                f"{trial[path_key]} at commit {trial['git_commit'][:12]} does not match the hash "
                f"recorded in {trial['trial_id']}"
            )
        frozen.append(data)
    return frozen[0], frozen[1]
