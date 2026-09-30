#!/usr/bin/env python3
"""PreToolUse hook: block any file write outside an agent's allowed paths (SPEC Section 8).

Usage (from an agent file's frontmatter): ``path_allow.py '<glob>' ['<glob>' ...]``. Globs are
relative to the agent root: ``$LAB_AGENT_ROOT`` when set (the isolated demo sandbox), otherwise
``$CLAUDE_PROJECT_DIR``, otherwise the working directory. ``*`` does not cross ``/``; ``**`` does.

The hook reads the tool call as JSON on stdin and exits 2 (which blocks the call and shows stderr
to the agent) unless every file the call would write is inside the root, matches a glob, and is
not on the hard-deny list. It fails closed: unreadable input, an unknown edit-tool shape or a
missing path all block. Standard library only, so it runs on any ``python3``.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# Never writable by a research-loop agent, even if a glob in its own file would match.
HARD_DENY = (
    "config/**",
    "core/judge/**",
    "ledger/**",
    ".claude/**",
    "data/holdout.enc",
    "results/holdout/**",
)

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
PATH_KEYS = ("file_path", "notebook_path", "path")


def glob_to_regex(pattern: str) -> re.Pattern:
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def matches(rel: str, patterns) -> bool:
    rel = rel.casefold()
    return any(glob_to_regex(p.casefold()).match(rel) for p in patterns)


def agent_root() -> Path:
    raw = os.environ.get("LAB_AGENT_ROOT") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return Path(raw).resolve()


def project_root() -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()


def check_path(raw: str, allowed, root: Path, base: Path):
    """Return None if ``raw`` may be written, else a reason string."""
    path = Path(raw)
    if not path.is_absolute():
        path = base / path
    resolved = path.resolve()  # follows symlinks and ``..`` so neither can smuggle a path out
    full, base_s = resolved.as_posix().casefold(), root.as_posix().casefold().rstrip("/")
    if not full.startswith(base_s + "/"):
        return f"{raw} is outside the agent root {root}"
    rel = full[len(base_s) + 1 :]
    if matches(rel, HARD_DENY):
        return f"{rel} is protected (config/, core/judge/, ledger/, .claude/ and hold-out files)"
    if not matches(rel, allowed):
        return f"{rel} does not match this agent's allowed paths: {', '.join(allowed)}"
    return None


def targets(tool_input: dict):
    found = [tool_input[k] for k in PATH_KEYS if isinstance(tool_input.get(k), str)]
    for edit in tool_input.get("edits") or []:
        if isinstance(edit, dict):
            found += [edit[k] for k in PATH_KEYS if isinstance(edit.get(k), str)]
    return found


def decide(payload: dict, allowed) -> str | None:
    """None to allow the tool call, else the reason to block it."""
    tool = payload.get("tool_name")
    if tool not in EDIT_TOOLS:
        return None
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return f"{tool}: no tool_input to check"
    paths = targets(tool_input)
    if not paths:
        return f"{tool}: no file path in the call, so it cannot be checked"
    base = Path(payload.get("cwd") or os.getcwd())
    root = agent_root()
    for raw in paths:
        # Hard-deny paths are relative to the project root even when the agent root is a sandbox.
        reason = check_path(raw, allowed, root, base)
        if reason is None and root != project_root():
            proj_reason = check_path(raw, ["**"], project_root(), base)
            if proj_reason and "protected" in proj_reason:
                reason = proj_reason
        if reason:
            return reason
    return None


def main(argv) -> int:
    allowed = argv[1:]
    if not allowed:
        print("path_allow.py: no allowed globs given; blocking", file=sys.stderr)
        return 2
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("hook input is not a JSON object")
    except ValueError as exc:
        print(f"path_allow.py: unreadable hook input ({exc}); blocking", file=sys.stderr)
        return 2
    reason = decide(payload, allowed)
    if reason:
        print(f"BLOCKED by path_allow: {reason}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
