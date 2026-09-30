#!/usr/bin/env python3
"""Helpers for ``scripts/loop.sh`` (SPEC Section 9.5). Standard library plus PyYAML only.

Subcommands:

* ``next-ids N``: the next N unused hypothesis ids (specs in the hypotheses dir and the ledger).
* ``spec-files H-XXXX ...``: JSON with each spec's and signal module's path.
* ``review-status FILE PHASE``: ``clear`` / ``block`` / ``missing`` from the skeptic's last
  ``Recommendation (PHASE): ...`` line. A missing review or line is never ``clear``.
* ``verdict H-XXXX``: the train verdict in ``results/H-XXXX/verdict.json``.
* ``run-agent``: run one research-loop agent headless and write its invocation log to ``logs/``.

Directories follow the same environment overrides as ``lab``: ``LAB_HYPOTHESES_DIR``,
``LAB_LEDGER_DIR``, ``LAB_RESULTS_DIR``.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_SKIP_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
}
SNAPSHOT_SKIP_TOP = {"data", "logs", "demo", ".lavish"}  # top level of each snapshot root only
ID_RE = re.compile(r"^H-(\d{4})(?:_.*)?\.ya?ml$")


def hypotheses_dir() -> Path:
    return Path(os.environ.get("LAB_HYPOTHESES_DIR") or REPO_ROOT / "hypotheses")


def ledger_dir() -> Path:
    return Path(os.environ.get("LAB_LEDGER_DIR") or REPO_ROOT / "ledger")


def results_dir() -> Path:
    return Path(os.environ.get("LAB_RESULTS_DIR") or REPO_ROOT / "results")


def used_numbers() -> set[int]:
    numbers = {
        int(m.group(1)) for p in hypotheses_dir().glob("H-*.y*ml") if (m := ID_RE.match(p.name))
    }
    trials = ledger_dir() / "trials.jsonl"
    if trials.exists():
        for line in trials.read_text().splitlines():
            if line.strip():
                numbers.add(int(json.loads(line)["hypothesis_id"].split("-")[1]))
    return numbers


def next_ids(n: int) -> list[str]:
    start = max(used_numbers() | {0}) + 1
    return [f"H-{i:04d}" for i in range(start, start + n)]


def find_spec(hid: str) -> Path:
    matches = sorted(hypotheses_dir().glob(f"{hid}_*.yaml")) + sorted(
        hypotheses_dir().glob(f"{hid}.yaml")
    )
    if len(matches) != 1:
        raise SystemExit(
            f"{hid}: expected exactly one spec file, found {[m.name for m in matches]}"
        )
    return matches[0]


def spec_files(ids: list[str]) -> list[dict]:
    import yaml

    out = []
    for hid in ids:
        spec_path = find_spec(hid)
        signal = yaml.safe_load(spec_path.read_text()).get("signal_module")
        if not isinstance(signal, str):
            raise SystemExit(f"{spec_path.name}: no signal_module")
        signal_path = (
            Path(signal) if Path(signal).is_absolute() else hypotheses_dir().parent / signal
        )
        if not signal_path.exists():
            raise SystemExit(f"{hid}: signal module {signal_path} does not exist")
        out.append({"id": hid, "spec": str(spec_path), "signal": str(signal_path)})
    return out


def review_status(path: Path, phase: str) -> str:
    if not path.exists():
        return "missing"
    pattern = re.compile(rf"^Recommendation \({re.escape(phase)}-run\): (clear|block)\s*$")
    found = [m.group(1) for line in path.read_text().splitlines() if (m := pattern.match(line))]
    return found[-1] if found else "missing"


def train_verdict(hid: str) -> str:
    path = results_dir() / hid / "verdict.json"
    if not path.exists():
        return "missing"
    return str(json.loads(path.read_text()).get("train_verdict"))


def snapshot(roots: list[Path]) -> dict[str, tuple[int, int]]:
    """(mtime_ns, size) of every file under ``roots``, minus caches, ``data/`` and ``logs/``."""
    seen: dict[str, tuple[int, int]] = {}
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            rel_dir = Path(dirpath).relative_to(root)
            top = SNAPSHOT_SKIP_TOP if rel_dir == Path(".") else set()
            skip = SNAPSHOT_SKIP_DIRS | top
            dirnames[:] = [d for d in dirnames if d not in skip]
            for name in filenames:
                path = Path(dirpath) / name
                try:
                    st = path.stat()
                except OSError:
                    continue
                seen[str(path)] = (st.st_mtime_ns, st.st_size)
    return seen


def diff_snapshots(before: dict, after: dict) -> dict[str, list[str]]:
    return {
        "created": sorted(set(after) - set(before)),
        "modified": sorted(p for p in after if p in before and after[p] != before[p]),
        "deleted": sorted(set(before) - set(after)),
    }


def _hook_module():
    spec = importlib.util.spec_from_file_location(
        "path_allow", REPO_ROOT / ".claude" / "hooks" / "path_allow.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def unexpected(paths: list[str], root: Path, globs: list[str]) -> list[str]:
    bad = []
    for p in paths:
        try:
            rel = Path(p).resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            bad.append(p)
            continue
        if not _hook_module().matches(rel, globs):
            bad.append(p)
    return bad


def run_agent(args: argparse.Namespace) -> int:
    prompt = Path(args.prompt_file).read_text()
    lab_root = Path(args.lab_root).resolve()
    claude = os.environ.get("LOOP_CLAUDE_CMD", "claude").split()
    cmd = [
        *claude,
        "-p",
        "--agent",
        args.agent,
        "--permission-mode",
        "acceptEdits",
        "--output-format",
        "json",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--max-budget-usd",
        os.environ.get("LOOP_MAX_BUDGET_USD", "3"),
    ]
    if lab_root != REPO_ROOT:
        cmd += ["--add-dir", str(lab_root)]
    for tool in args.allowed_tool:
        cmd += ["--allowedTools", tool]
    if os.environ.get("LOOP_AGENT_MODEL"):
        cmd += ["--model", os.environ["LOOP_AGENT_MODEL"]]
    # The prompt goes on stdin: --mcp-config and --allowedTools are variadic and would swallow it.

    env = {k: v for k, v in os.environ.items() if k != "LAB_HOLDOUT_KEY"}  # never in agent sessions
    env["LAB_AGENT_ROOT"] = str(lab_root)
    roots = [REPO_ROOT] + ([lab_root] if lab_root != REPO_ROOT else [])
    before = snapshot(roots)
    started = datetime.now(UTC)
    t0 = time.monotonic()
    proc = subprocess.run(cmd, cwd=REPO_ROOT, env=env, input=prompt, capture_output=True, text=True)
    duration = time.monotonic() - t0
    touched = diff_snapshots(before, snapshot(roots))
    changed = touched["created"] + touched["modified"] + touched["deleted"]
    stray = unexpected(changed, lab_root, args.expect_glob)
    try:
        payload = json.loads(proc.stdout)
    except ValueError:
        payload = {}
    if isinstance(payload, list):  # some versions emit the event array
        payload = next((e for e in reversed(payload) if e.get("type") == "result"), {})
    record = {
        "step": args.step,
        "agent": args.agent,
        "started_at": started.isoformat(),
        "duration_s": round(duration, 2),
        "exit_code": proc.returncode,
        "prompt": prompt,
        "command": cmd,
        "files_touched": touched,
        "expected_globs": args.expect_glob,
        "unexpected_files": stray,
        "permission_denials": payload.get("permission_denials", []),
        "cost_usd": payload.get("total_cost_usd"),
        "num_turns": payload.get("num_turns"),
        "session_id": payload.get("session_id"),
        "result": payload.get("result"),
        "stderr_tail": proc.stderr[-2000:],
    }
    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / f"{args.step}.json").write_text(json.dumps(record, indent=2) + "\n")
    print(
        f"[{args.step}] {args.agent}: exit {proc.returncode}, {duration:.0f}s, "
        f"{len(changed)} files touched, {len(record['permission_denials'])} denied"
    )
    if stray:
        print(f"[{args.step}] UNEXPECTED FILES touched by {args.agent}: {stray}", file=sys.stderr)
        return 3
    return proc.returncode


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("next-ids")
    p.add_argument("n", type=int)
    p = sub.add_parser("spec-files")
    p.add_argument("ids", nargs="+")
    p = sub.add_parser("review-status")
    p.add_argument("file")
    p.add_argument("phase", choices=["pre", "post"])
    p = sub.add_parser("verdict")
    p.add_argument("id")
    p = sub.add_parser("run-agent")
    p.add_argument("--agent", required=True)
    p.add_argument("--step", required=True)
    p.add_argument("--prompt-file", required=True)
    p.add_argument("--log-dir", required=True)
    p.add_argument("--lab-root", default=str(REPO_ROOT))
    p.add_argument("--expect-glob", action="append", default=[])
    p.add_argument("--allowed-tool", action="append", default=[])
    args = ap.parse_args(argv)
    if args.cmd == "next-ids":
        print(" ".join(next_ids(args.n)))
    elif args.cmd == "spec-files":
        print(json.dumps(spec_files(args.ids)))
    elif args.cmd == "review-status":
        print(review_status(Path(args.file), args.phase))
    elif args.cmd == "verdict":
        print(train_verdict(args.id))
    else:
        return run_agent(args)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
