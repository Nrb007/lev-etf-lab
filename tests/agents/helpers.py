"""Shared helpers: load the real agent files and run their declared hook commands."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
AGENTS_DIR = REPO / ".claude" / "agents"
AGENT_NAMES = ["hypothesis", "data", "skeptic", "report"]


def load_agent(name: str) -> dict:
    """Frontmatter of ``.claude/agents/<name>.md`` (the file Claude Code itself reads)."""
    text = (AGENTS_DIR / f"{name}.md").read_text()
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert match, f"{name}.md has no frontmatter"
    return yaml.safe_load(match.group(1))


def tool_names(agent: dict) -> list[str]:
    raw = agent["tools"]
    items = raw if isinstance(raw, list) else str(raw).split(",")
    return [item.strip() for item in items]


def hook_command(agent: dict, tool: str) -> str:
    """The command of the PreToolUse hook whose matcher covers ``tool``."""
    for entry in agent.get("hooks", {}).get("PreToolUse", []):
        if tool in entry["matcher"].split("|"):
            (hook,) = entry["hooks"]
            assert hook["type"] == "command"
            return hook["command"]
    raise AssertionError(f"no PreToolUse hook covers {tool}")


def run_hook(command: str, payload, root: Path, agent_root: Path | None = None):
    """Run a hook command line exactly as Claude Code would: JSON on stdin, project dir set."""
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root)}
    env.pop("LAB_AGENT_ROOT", None)
    if agent_root is not None:
        env["LAB_AGENT_ROOT"] = str(agent_root)
    stdin = payload if isinstance(payload, str) else json.dumps({"cwd": str(root), **payload})
    return subprocess.run(
        command, shell=True, input=stdin, capture_output=True, text=True, env=env, cwd=root
    )


def write_call(path: str, tool: str = "Write") -> dict:
    return {"tool_name": tool, "tool_input": {"file_path": path, "content": "x"}}
