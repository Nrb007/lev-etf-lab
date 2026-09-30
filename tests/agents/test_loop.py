"""Structural tests for scripts/loop.sh: sequencing and CLI wiring, with stand-ins for the model.

CI has no credentials and a live agent costs money and is not deterministic, so `claude` and `lab`
are replaced by small stubs (``LOOP_CLAUDE_CMD``, ``LAB_CMD``) that record every call in order. The
real ``scripts/loop.sh`` and ``scripts/loop_tools.py`` run unmodified. What these tests prove is the
order of the nine steps, the stop conditions, the human-only hold-out, log writing and that
``LAB_HOLDOUT_KEY`` never reaches an agent. The live iteration is recorded in docs/evidence/m5/.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.agents.helpers import REPO

STUB_CLAUDE = r"""
import json, os, re, sys
from datetime import date
from pathlib import Path

argv = sys.argv[1:]
agent = argv[argv.index("--agent") + 1]
prompt = sys.stdin.read()
root = Path(re.search(r"Lab root: (\S+?)(?: \(|\.\s)", prompt).group(1))
hyp = Path(os.environ.get("LAB_HYPOTHESES_DIR") or root / "hypotheses")
results = Path(os.environ.get("LAB_RESULTS_DIR") or root / "results")
log = Path(os.environ["STUB_LOG"])
with log.open("a") as f:
    f.write(f"claude {agent} key_visible={'LAB_HOLDOUT_KEY' in os.environ} "
            f"add_dir={'--add-dir' in argv}\n")
overrides = dict(x.split("=") for x in os.environ.get("STUB_SKEPTIC", "").split(",") if x)
if agent == "hypothesis":
    ids = re.search(r"these ids: ((?:H-\d{4} ?)+)\.", prompt).group(1).split()
    for n, hid in enumerate(ids):
        num = hid[2:]
        (hyp / f"{hid}_stub.yaml").write_text(
            f"id: {hid}\nsignal_module: hypotheses/signals/h{num}_stub.py\n")
        (hyp / "signals" / f"h{num}_stub.py").write_text("# stub signal\n")
    if os.environ.get("STUB_EVIL"):
        evil = root / "core" / "judge"
        evil.mkdir(parents=True, exist_ok=True)
        (evil / "evil.py").write_text("x = 1\n")
elif agent == "skeptic":
    hid = re.search(r"review of (H-\d{4})", prompt).group(1)
    phase = "pre" if prompt.startswith("Pre-run") else "post"
    verdict = overrides.get(hid, "clear")
    review = results / hid / "review.md"
    review.parent.mkdir(parents=True, exist_ok=True)
    old = review.read_text() if review.exists() else ""
    tail = "" if verdict == "none" else f"Recommendation ({phase}-run): {verdict}\n"
    review.write_text(old + f"## {phase} review - {hid}\n\nFindings:\n- stub\n\n" + tail)
elif agent == "report":
    hid = re.search(r"report for (H-\d{4})", prompt).group(1)
    (results / hid / "report.md").write_text("stub report\n")
print(json.dumps({"type": "result", "result": "ok", "total_cost_usd": 0.01,
                  "num_turns": 2, "session_id": "stub", "permission_denials": []}))
"""

STUB_LAB = r"""
import json, os, sys
from pathlib import Path

args = sys.argv[1:]
with Path(os.environ["STUB_LOG"]).open("a") as f:
    f.write("lab " + " ".join(args) + f" key_visible={'LAB_HOLDOUT_KEY' in os.environ}\n")
if args[:2] == ["ledger", "summary"]:
    print("N = 0 trials across 0 hypotheses")
elif args[0] == "judge":
    out = Path(os.environ["LAB_RESULTS_DIR"]) / args[1]
    out.mkdir(parents=True, exist_ok=True)
    verdict = os.environ.get("STUB_VERDICT", "reject")
    (out / "verdict.json").write_text(json.dumps({"train_verdict": verdict}))
elif args[0] == "run" and os.environ.get("STUB_RUN_FAILS") == args[1]:
    sys.exit(1)
"""


@pytest.fixture
def env(tmp_path):
    (tmp_path / "claude.py").write_text(STUB_CLAUDE)
    (tmp_path / "lab.py").write_text(STUB_LAB)
    log = tmp_path / "calls.log"
    sandbox = tmp_path / "sandbox"
    variables = {
        **os.environ,
        "STUB_LOG": str(log),
        "LOOP_CLAUDE_CMD": f"{sys.executable} {tmp_path / 'claude.py'}",
        "LAB_CMD": f"{sys.executable} {tmp_path / 'lab.py'}",
        "LOOP_TOOLS_CMD": f"{sys.executable} {REPO / 'scripts' / 'loop_tools.py'}",
        "LOOP_LOG_DIR": str(tmp_path / "logs"),
        "LOOP_AUTO_COMMIT": "1",
        "LAB_HOLDOUT_KEY": "must-never-reach-an-agent",
    }
    for key in ("LAB_HYPOTHESES_DIR", "LAB_LEDGER_DIR", "LAB_RESULTS_DIR", "LAB_AGENT_ROOT"):
        variables.pop(key, None)
    return {"vars": variables, "log": log, "sandbox": sandbox, "tmp": tmp_path}


def loop(env, *args, extra=None, sandbox=True):
    cmd = ["bash", str(REPO / "scripts" / "loop.sh"), *args]
    if sandbox:
        cmd += ["--sandbox", str(env["sandbox"])]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        env={**env["vars"], **(extra or {})},
        timeout=120,
    )


def calls(env) -> list[str]:
    return env["log"].read_text().splitlines() if env["log"].exists() else []


def shape(call: str) -> str:
    return re.sub(r" key_visible=\w+| add_dir=\w+", "", call)


def test_full_iteration_runs_the_nine_steps_in_order(env):
    result = loop(env, "--n-new", "2")
    assert result.returncode == 0, result.stdout + result.stderr
    assert [shape(c) for c in calls(env)] == [
        "lab ledger summary",
        "claude hypothesis",
        "claude skeptic",
        "claude skeptic",
        "lab run H-0001",
        "lab judge H-0001",
        "lab run H-0002",
        "lab judge H-0002",
        "claude skeptic",
        "claude skeptic",
        "claude report",
        "claude report",
        "lab dashboard build",
        "lab ledger summary",
    ]
    # step 3: both specs were committed in the sandbox repo before the run
    head = subprocess.run(
        ["git", "-C", str(env["sandbox"]), "log", "-1", "--format=%s"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert head == "register H-0001 H-0002"
    status = subprocess.run(
        ["git", "-C", str(env["sandbox"]), "status", "--porcelain", "--", "hypotheses"],
        capture_output=True,
        text=True,
    ).stdout
    assert status == ""


def test_sandbox_never_touches_the_real_hypotheses_or_ledger(env):
    before = sorted(p.name for p in (REPO / "hypotheses").iterdir())
    ledger_before = (REPO / "ledger" / "trials.jsonl").read_bytes()
    assert loop(env, "--n-new", "1").returncode == 0
    assert sorted(p.name for p in (REPO / "hypotheses").iterdir()) == before
    assert (REPO / "ledger" / "trials.jsonl").read_bytes() == ledger_before
    assert (env["sandbox"] / "hypotheses" / "H-0001_stub.yaml").exists()
    assert (env["sandbox"] / "results" / "H-0001" / "report.md").exists()


def test_skeptic_block_stops_before_any_run(env):
    result = loop(env, "--n-new", "2", extra={"STUB_SKEPTIC": "H-0001=block,H-0002=block"})
    assert result.returncode == 1
    assert "BLOCKED by the skeptic" in result.stdout
    assert not [c for c in calls(env) if c.startswith("lab run")]
    assert not (env["sandbox"] / "results" / "H-0001" / "report.md").exists()


def test_a_missing_recommendation_line_counts_as_block(env):
    result = loop(env, "--n-new", "1", extra={"STUB_SKEPTIC": "H-0001=none"})
    assert result.returncode == 1
    assert not [c for c in calls(env) if c.startswith("lab run")]


def test_only_cleared_specs_are_run(env):
    result = loop(env, "--n-new", "2", extra={"STUB_SKEPTIC": "H-0002=block"})
    assert result.returncode == 0, result.stdout + result.stderr
    runs = [c for c in calls(env) if c.startswith("lab run")]
    assert [shape(c) for c in runs] == ["lab run H-0001"]
    head = subprocess.run(
        ["git", "-C", str(env["sandbox"]), "log", "-1", "--format=%s"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert head == "register H-0001"  # the blocked spec is not registered


def test_override_needs_an_interactive_terminal(env):
    result = loop(
        env, "--n-new", "1", "--override-block", "H-0001", extra={"STUB_SKEPTIC": "H-0001=block"}
    )
    assert result.returncode == 1
    assert "override needs an interactive terminal" in result.stdout
    assert not [c for c in calls(env) if c.startswith("lab run")]


@pytest.mark.parametrize("verdict", ["advance", "reject"])
def test_holdout_is_never_reachable_from_a_sandbox_or_a_pipe(env, verdict):
    result = loop(env, "--n-new", "2", extra={"STUB_VERDICT": verdict})
    assert result.returncode == 0, result.stdout + result.stderr
    assert not [c for c in calls(env) if "holdout" in shape(c).replace("claude", "")]
    if verdict == "advance":
        assert "never scored from a sandbox" in result.stdout


def test_real_mode_without_a_terminal_stops_at_the_checkpoint(env, tmp_path):
    """No --sandbox and no tty: the human checkpoint refuses, so nothing is committed or run."""
    repo = tmp_path / "labrepo"
    (repo / "hypotheses" / "signals").mkdir(parents=True)
    subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True)
    extra = {
        "LAB_HYPOTHESES_DIR": str(repo / "hypotheses"),
        "LAB_LEDGER_DIR": str(tmp_path / "ledger"),
        "LAB_RESULTS_DIR": str(tmp_path / "results"),
        "LOOP_AUTO_COMMIT": "",
    }
    (tmp_path / "ledger").mkdir()
    env["vars"].pop("LOOP_AUTO_COMMIT")
    result = loop(env, "--n-new", "1", extra=extra, sandbox=False)
    assert result.returncode == 1
    assert "needs a human at a terminal" in result.stderr
    assert not [c for c in calls(env) if c.startswith("lab run")]
    log = subprocess.run(
        ["git", "-C", str(repo), "log", "--oneline"], capture_output=True, text=True
    )
    assert log.stdout.strip() == ""  # no commit


def test_auto_commit_is_refused_outside_a_sandbox(env):
    result = loop(env, sandbox=False, extra={"LOOP_AUTO_COMMIT": "1"})
    assert result.returncode == 2
    assert "only allowed with --sandbox" in result.stderr
    assert calls(env) == []


def test_holdout_key_never_reaches_an_agent_or_the_cli(env):
    assert loop(env, "--n-new", "1").returncode == 0
    assert calls(env)
    assert all("key_visible=False" in c for c in calls(env))


def test_every_agent_invocation_is_logged(env):
    assert loop(env, "--n-new", "1").returncode == 0
    (run_dir,) = (env["tmp"] / "logs").iterdir()
    records = [json.loads(p.read_text()) for p in sorted(run_dir.glob("*.json"))]
    assert [r["agent"] for r in records] == ["hypothesis", "skeptic", "skeptic", "report"]
    for record in records:
        assert record["prompt"] and record["duration_s"] >= 0 and record["exit_code"] == 0
        assert {"created", "modified", "deleted"} == set(record["files_touched"])
        assert record["unexpected_files"] == []
    created = [Path(p).name for p in records[0]["files_touched"]["created"]]
    assert sorted(created) == ["H-0001_stub.yaml", "h0001_stub.py"]
    assert any(p.endswith("review.md") for p in records[1]["files_touched"]["created"])


def test_a_write_outside_the_agent_scope_is_detected_and_stops_the_loop(env):
    """The after-the-fact audit that backs up the hook (e.g. a route the hook did not see)."""
    result = loop(env, "--n-new", "1", extra={"STUB_EVIL": "1"})
    assert result.returncode == 3
    assert "UNEXPECTED FILES" in result.stderr and "evil.py" in result.stderr
    assert not [c for c in calls(env) if c.startswith("lab run")]


def test_a_failed_run_is_reported_and_does_not_hide_the_others(env):
    result = loop(env, "--n-new", "2", extra={"STUB_RUN_FAILS": "H-0001"})
    assert result.returncode == 1
    assert "H-0001: run or judge failed" in result.stderr
    assert "lab judge H-0002" in [shape(c) for c in calls(env)]
    assert "lab judge H-0001" not in [shape(c) for c in calls(env)]


def test_loop_script_has_a_single_guarded_holdout_call():
    text = (REPO / "scripts" / "loop.sh").read_text()
    sites = [line for line in text.splitlines() if re.search(r"\blab holdout\b", line)
             and not line.lstrip().startswith("#") and "echo" not in line]  # fmt: skip
    assert len(sites) == 1 and "LAB_HOLDOUT_KEY" in sites[0]
    body = text[text.index("7/9 hold-out") : text.index("8/9 report")]
    assert '[ -n "$SANDBOX" ]' in body and "[ ! -t 0 ]" in body and "read -r" in body
    assert "--yes" not in text and "--force" not in text


def test_audit_also_covers_a_sandbox_nested_inside_the_repo(env):
    """The demo sandbox lives in the repo's (gitignored) demo/ dir; its files must be audited."""
    nested = REPO / "demo" / f"pytest-sandbox-{os.getpid()}"
    env["sandbox"] = nested
    try:
        result = loop(env, "--n-new", "1", extra={"STUB_EVIL": "1"})
        assert result.returncode == 3
        assert "evil.py" in result.stderr
        (run_dir,) = (env["tmp"] / "logs").iterdir()
        record = json.loads((run_dir / "01-hypothesis.json").read_text())
        created = [Path(p).name for p in record["files_touched"]["created"]]
        assert {"H-0001_stub.yaml", "h0001_stub.py", "evil.py"} <= set(created)
    finally:
        shutil.rmtree(nested, ignore_errors=True)
