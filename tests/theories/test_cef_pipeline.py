"""The CEF package through the unchanged engine, ledger and judge (SPEC Sections 1.6, 15)."""

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from typer.testing import CliRunner

from core import judge_runner
from core.cli import app
from core.data import cache
from core.ledger import ledger
from tests.prereg_helpers import commit_all, init_repo, write_spec

runner = CliRunner()
ROOT = Path(__file__).resolve().parents[2]
SPEC_REL = "hypotheses/H-0001_cef_discount_reversion.yaml"
SIGNAL_REL = "theories/cef/signals/premium_reversion.py"


@pytest.fixture
def cef_env(cef_pulled, monkeypatch, tmp_path):
    monkeypatch.setenv("LAB_DATA_DIR", str(cef_pulled["tmp_path"]))
    monkeypatch.setenv("LAB_LEDGER_DIR", str(tmp_path / "ledger"))
    monkeypatch.setenv("LAB_RESULTS_DIR", str(tmp_path / "results"))
    repo = init_repo(tmp_path / "repo")
    monkeypatch.setenv("LAB_HYPOTHESES_DIR", str(repo / "hypotheses"))
    for rel in (SPEC_REL, SIGNAL_REL):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, repo / rel)
    commit_all(repo, "register H-0001", date="2019-01-02T00:00:00+00:00")
    return repo


def test_the_registered_spec_runs_through_lab_run_and_counts_its_grid(cef_env):
    result = runner.invoke(app, ["run", "H-0001", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["n_grid_points"] == 9 and payload["n_trials_total"] == 9
    trials = ledger.read_trials()
    assert {t["universe"]["fund"] for t in trials} == {"ADX"}
    assert {(t["params"]["window"], t["params"]["entry_z"]) for t in trials} == {
        (w, z) for w in (63, 126, 252) for z in (0.5, 1.0, 1.5)
    }
    assert all(t["signal_path"] == SIGNAL_REL for t in trials)


def test_the_leakage_command_clears_the_registered_signal(cef_env):
    result = runner.invoke(app, ["leakage", "H-0001", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["grid_points"] == 9


def test_n_counts_trials_across_both_theory_packages_in_one_ledger(cef_env):
    write_spec(cef_env, "H-9999")  # the leveraged-ETF package's test hypothesis: 3 grid points
    assert runner.invoke(app, ["run", "H-9999"]).exit_code == 0
    result = runner.invoke(app, ["run", "H-0001", "--json"])
    assert json.loads(result.output)["n_trials_total"] == 12  # 3 + 9, one N
    trials = ledger.read_trials()
    assert [t["n"] for t in trials] == list(range(1, 13))
    assert {t["universe"]["fund"] for t in trials} == {"TQQQ", "ADX"}
    # the judge's inputs carry both packages' trials, so every N-based correction sees all 12
    assert ledger.count_trials() == 12 and ledger.trial_matrix().shape[1] == 12


def test_the_judge_runs_on_a_cef_hypothesis(cef_env):
    assert runner.invoke(app, ["run", "H-0001"]).exit_code == 0
    result = runner.invoke(app, ["judge", "H-0001", "--json"])
    assert result.exit_code == 0, result.output
    verdict = json.loads(result.output)
    assert verdict["train_verdict"] in {"advance", "reject"}
    assert verdict["hypothesis_id"] == "H-0001"


def test_hold_out_scoring_refuses_a_cef_hypothesis_without_using_the_attempt(cef_env, monkeypatch):
    assert runner.invoke(app, ["run", "H-0001"]).exit_code == 0
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(judge_runner, "os", SimpleNamespace(environ={"LAB_HOLDOUT_KEY": key}))
    with pytest.raises(judge_runner.RunError, match="hold-out file has no data"):
        judge_runner.holdout_hypothesis("H-0001")
    assert ledger.read_holdout_attempts() == []
    assert not cache.holdout_path().exists()


def test_core_engine_and_judge_do_not_mention_closed_end_funds():
    text = "\n".join(
        p.read_text().lower() for d in ("engine", "judge") for p in (ROOT / "core" / d).glob("*.py")
    )
    for word in ("cef", "closed-end", "closed end", "premium", "discount to nav", "theories"):
        assert word not in text, word
