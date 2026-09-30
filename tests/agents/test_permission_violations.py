"""Deliberate attempts to violate each agent's scope (SPEC Section 12, Milestone 5).

Each test runs the PreToolUse hook command exactly as it is declared in the real agent file, with
the JSON a Claude Code tool call would send. This is the same hook path a live agent triggers
(the live check is ``test_live_agents.py``, skipped unless LAB_LIVE_AGENT_TESTS=1); it needs no
credentials and no model, so it runs in CI.
"""

import shutil

import pytest

from tests.agents.helpers import (
    AGENT_NAMES,
    REPO,
    hook_command,
    load_agent,
    run_hook,
    tool_names,
    write_call,
)

ALLOWED = {
    "hypothesis": ["hypotheses/H-0042_vol.yaml", "hypotheses/signals/h0042_vol.py"],
    "data": [
        "core/data/loaders.py",
        "core/data/new/mod.py",
        "data/cache/QQQ.parquet",
        "results/data_validation.json",
    ],  # fmt: skip
    "skeptic": ["results/H-0042/review.md"],
    "report": ["results/H-0042/report.md"],
}

# Paths no research-loop agent may write, whatever its own scope is.
PROTECTED = [
    "core/judge/verdict.py",
    "core/judge/dsr.py",
    "config/thresholds.yaml",
    "config/lab.yaml",
    "ledger/trials.jsonl",
    "ledger/returns/T-000001.parquet",
    ".claude/settings.json",
    ".claude/agents/hypothesis.md",
    ".claude/hooks/path_allow.py",
    "data/holdout.enc",
    "results/holdout/H-0042.json",
    "core/cli.py",
    "SPEC.md",
    "CLAUDE.md",
    "tests/test_cli.py",
    "scripts/loop.sh",
]


def blocked(result) -> bool:
    """Exit 2 with the hook's own message, so a crashed or missing script cannot pass as a block."""
    return result.returncode == 2 and ("BLOCKED by" in result.stderr or "blocking" in result.stderr)


def writer_hook(name: str, tool: str = "Write") -> str:
    return hook_command(load_agent(name), tool)


@pytest.fixture
def root(tmp_path):
    """A stand-in project root: the hook only needs paths, not real files."""
    (tmp_path / "hypotheses" / "signals").mkdir(parents=True)
    (tmp_path / "core" / "judge").mkdir(parents=True)
    shutil.copytree(REPO / ".claude" / "hooks", tmp_path / ".claude" / "hooks")
    return tmp_path


@pytest.mark.parametrize("name", AGENT_NAMES)
@pytest.mark.parametrize("path", PROTECTED)
@pytest.mark.parametrize("tool", ["Write", "Edit"])
def test_agent_cannot_write_protected_paths(name, path, tool, root):
    if tool not in tool_names(load_agent(name)):
        pytest.skip(f"{name} has no {tool}")
    result = run_hook(writer_hook(name, tool), write_call(str(root / path), tool), root)
    assert blocked(result), (name, path, result.stderr)


@pytest.mark.parametrize("name", AGENT_NAMES)
def test_agent_can_write_its_own_paths(name, root):
    for path in ALLOWED[name]:
        result = run_hook(writer_hook(name), write_call(str(root / path)), root)
        assert result.returncode == 0, (name, path, result.stderr)


@pytest.mark.parametrize("name", AGENT_NAMES)
def test_agents_cannot_write_each_others_paths(name, root):
    for other, paths in ALLOWED.items():
        if other == name:
            continue
        for path in paths:
            result = run_hook(writer_hook(name), write_call(str(root / path)), root)
            assert blocked(result), (name, other, path)


def test_hypothesis_attempts_on_the_judge_are_blocked_in_every_spelling(root):
    hook = writer_hook("hypothesis")
    (root / "core" / "judge" / "verdict.py").write_text("x")
    (root / "hypotheses" / "link").symlink_to(root / "core" / "judge")
    attempts = [
        "core/judge/verdict.py",  # relative to cwd
        str(root / "core" / "judge" / "verdict.py"),
        str(root / "hypotheses" / ".." / "core" / "judge" / "new.py"),  # traversal
        str(root / "hypotheses" / "signals" / ".." / ".." / "config" / "thresholds.yaml"),
        str(root / "hypotheses" / "link" / "verdict.py"),  # symlink out of the allowed dir
        "/etc/hosts",
        str(root.parent / "elsewhere.yaml"),  # outside the project
        str(root / "hypotheses" / "signals" / "nested" / "x.py"),  # * does not cross /
        str(root / "hypotheses" / "notes.txt"),
        str(root / "hypotheses" / "H-0001.yaml.sh"),
    ]
    for path in attempts:
        result = run_hook(hook, write_call(path), root)
        assert blocked(result), path


def test_hook_covers_multiedit_and_notebook_shapes(root):
    hook = writer_hook("hypothesis")
    multi = {
        "tool_name": "MultiEdit",
        "tool_input": {
            "file_path": str(root / "hypotheses" / "H-0001_a.yaml"),
            "edits": [{"file_path": str(root / "core" / "judge" / "x.py"), "old": "a", "new": "b"}],
        },
    }
    assert blocked(run_hook(hook, multi, root))
    note = {"tool_name": "NotebookEdit", "tool_input": {"notebook_path": str(root / "a.ipynb")}}
    assert blocked(run_hook(hook, note, root))


@pytest.mark.parametrize(
    "stdin",
    [
        "",
        "not json",
        "[]",
        "null",
        '{"tool_name": "Write"}',
        '{"tool_name": "Write", "tool_input": 3}',
    ],
)
def test_hook_fails_closed_on_malformed_input(stdin, root):
    result = run_hook(writer_hook("hypothesis"), stdin, root)
    assert blocked(result)


def test_hook_without_globs_blocks_everything(root):
    command = f"python3 {REPO}/.claude/hooks/path_allow.py"
    result = run_hook(command, write_call(str(root / "hypotheses" / "H-0001_a.yaml")), root)
    assert blocked(result)


def test_non_edit_tools_pass_through(root):
    payload = {"tool_name": "Read", "tool_input": {"file_path": "/etc/hosts"}}
    assert run_hook(writer_hook("hypothesis"), payload, root).returncode == 0


def test_sandbox_root_moves_the_scope_and_keeps_the_real_repo_protected(root, tmp_path):
    sandbox = tmp_path / "sandbox"
    (sandbox / "hypotheses" / "signals").mkdir(parents=True)
    hook = writer_hook("hypothesis")
    ok = write_call(str(sandbox / "hypotheses" / "H-0001_a.yaml"))
    assert run_hook(hook, ok, root, agent_root=sandbox).returncode == 0
    # the project's own hypotheses dir is outside the sandbox root: isolation
    real = write_call(str(root / "hypotheses" / "H-0001_a.yaml"))
    assert blocked(run_hook(hook, real, root, agent_root=sandbox))
    # a sandbox ledger and the project's judge are both protected
    for path in (sandbox / "ledger" / "trials.jsonl", sandbox / "core" / "judge" / "x.py"):
        assert blocked(run_hook(hook, write_call(str(path)), root, agent_root=sandbox))
    judge = write_call(str(root / "core" / "judge" / "x.py"))
    assert blocked(run_hook(hook, judge, root, agent_root=sandbox))


def test_skeptic_bash_hook_allows_only_test_commands(root):
    hook = hook_command(load_agent("skeptic"), "Bash")

    def bash(command):
        return run_hook(hook, {"tool_name": "Bash", "tool_input": {"command": command}}, root)

    for ok in (
        "uv run pytest",
        "uv run pytest tests/test_cli.py -q -k leak",
        "uv run lab leakage H-0001",
    ):
        assert bash(ok).returncode == 0, ok
    for bad in (
        "rm -rf core/judge",
        "uv run lab run H-0001",
        "uv run lab holdout H-0001",
        "uv run lab judge H-0001",
        "cat data/holdout.enc",
        "uv run pytest; rm ledger/trials.jsonl",
        "uv run pytest && cat /etc/hosts",
        "uv run pytest > config/thresholds.yaml",
        "uv run pytest $(touch x)",
        "uv run pytest `id`",
        "uv run pytestx",
        "uv run lab leakage H-0001 | tee ledger/trials.jsonl",
        "echo hi",
        "",
    ):
        assert blocked(bash(bad)), bad
