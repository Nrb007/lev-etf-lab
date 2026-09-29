"""`lab judge` / `lab holdout` wiring against the recorded mini universe and a temporary ledger."""

import json
from types import SimpleNamespace

import pandas as pd
import pytest
from cryptography.fernet import Fernet
from typer.testing import CliRunner

from core import judge_runner
from core.cli import app
from core.config import load_thresholds
from core.data.splits import encrypt_holdout
from core.judge.holdout import score_holdout
from core.judge.verdict import TEST_ORDER, thresholds_hash
from core.runner import RunError
from tests.prereg_helpers import init_repo, write_spec

runner = CliRunner()


@pytest.fixture
def lab_env(pulled, monkeypatch, tmp_path):
    monkeypatch.setenv("LAB_DATA_DIR", str(pulled["tmp_path"]))
    monkeypatch.setenv("LAB_LEDGER_DIR", str(tmp_path / "ledger"))
    monkeypatch.setenv("LAB_RESULTS_DIR", str(tmp_path / "results"))
    repo = init_repo(tmp_path / "repo")
    monkeypatch.setenv("LAB_HYPOTHESES_DIR", str(repo / "hypotheses"))
    write_spec(repo)
    assert runner.invoke(app, ["run", "H-9999"]).exit_code == 0
    return tmp_path


def test_judge_writes_a_verdict_in_the_section_6_2_shape(lab_env):
    result = runner.invoke(app, ["judge", "H-9999", "--json"])
    assert result.exit_code == 0, result.output
    verdict = json.loads(result.output)
    assert verdict["hypothesis_id"] == "H-9999" and verdict["n_trials"] == 3
    assert set(verdict["tests"]) == set(TEST_ORDER)
    assert verdict["holdout_verdict"] is None
    assert verdict["thresholds_hash"] == thresholds_hash()
    # three trials are far below the PBO floor: reject, with the failing tests named
    assert verdict["train_verdict"] == "reject" and "pbo" in verdict["reasons"]
    assert verdict["tests"]["pbo"]["details"]["status"] == "insufficient_trials"
    assert verdict["reasons"] == [n for n in TEST_ORDER if not verdict["tests"][n]["pass"]]
    saved = json.loads((lab_env / "results" / "H-9999" / "verdict.json").read_text())
    assert saved == verdict


def test_judge_is_deterministic_through_the_cli(lab_env):
    first = runner.invoke(app, ["judge", "H-9999", "--json"]).output
    assert runner.invoke(app, ["judge", "H-9999", "--json"]).output == first


def test_judge_without_trials_fails_loudly(lab_env):
    result = runner.invoke(app, ["judge", "H-1234"])
    assert result.exit_code == 1 and "no spec file" in result.output


def test_judge_detects_a_ledger_that_no_longer_reproduces(lab_env, monkeypatch):
    path = lab_env / "ledger" / "trials.jsonl"
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    for rec in lines:
        rec["execution"]["cost_bps"] = 500.0  # ledger claims a config the returns don't match
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in lines))
    result = runner.invoke(app, ["judge", "H-9999"])
    assert result.exit_code == 1 and "does not reproduce" in result.output


def test_holdout_command_needs_a_key_and_a_train_advance(lab_env, monkeypatch):
    monkeypatch.delenv("LAB_HOLDOUT_KEY", raising=False)
    result = runner.invoke(app, ["holdout", "H-9999"])
    assert result.exit_code == 1 and "LAB_HOLDOUT_KEY" in result.output
    # a rejected hypothesis is never scored (disposable key injected only into this module)
    fake_os = SimpleNamespace(environ={"LAB_HOLDOUT_KEY": Fernet.generate_key().decode()})
    monkeypatch.setattr(judge_runner, "os", fake_os)
    with pytest.raises(RunError, match="reject"):
        judge_runner.holdout_hypothesis("H-9999")
    assert not (lab_env / "results" / "holdout").exists()


def test_holdout_plumbing_scores_the_frozen_signal_on_the_holdout_slice(lab_env, tmp_path):
    """Everything after the verdict gate: build features from the slice, run, judge, return."""
    key = Fernet.generate_key()
    ctx = judge_runner.prepare("H-9999")
    idx = pd.bdate_range("2019-10-01", periods=120)
    price = pd.Series(range(120), index=idx, dtype="float64") * 0.5 + 100
    frame = pd.DataFrame(
        {"TQQQ": price, "QQQ": price / 3, "^VIX": 20.0, "FRED:DGS3MO": 2.0, "FRED:DFF": 2.0}
    )
    path = tmp_path / "h.enc"
    encrypt_holdout(frame, key, path)
    out = score_holdout(
        "H-9999",
        judge_runner._holdout_run(ctx),
        0.05,
        load_thresholds().holdout,
        key=key,
        holdout_path=path,
        results_dir=tmp_path / "res",
    )
    assert set(out) == {"hypothesis_id", "holdout_verdict", "scored_at"}
    assert out["holdout_verdict"] in {"pass", "fail"}
    saved = json.loads((tmp_path / "res" / "holdout" / "H-9999.json").read_text())
    assert saved["n_obs"] == 119
