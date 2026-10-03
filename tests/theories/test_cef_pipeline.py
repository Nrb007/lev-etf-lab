"""The CEF package through the unchanged engine, ledger and judge (SPEC Sections 1.6, 15)."""

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from cryptography.fernet import Fernet
from typer.testing import CliRunner

from core import judge_runner
from core.cli import app
from core.data import cache
from core.data.splits import encrypt_holdout
from core.ledger import ledger
from tests.prereg_helpers import commit_all, init_repo, write_spec

runner = CliRunner()
ROOT = Path(__file__).resolve().parents[2]
SPEC_REL = "hypotheses/H-0002_cef_discount_reversion.yaml"
SIGNAL_REL = "theories/cef/signals/discount_zscore.py"


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
    commit_all(repo, "register H-0002", date="2019-01-02T00:00:00+00:00")
    return repo


def test_the_registered_spec_runs_through_lab_run_and_counts_its_grid(cef_env):
    result = runner.invoke(app, ["run", "H-0002", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["n_grid_points"] == 9 and payload["n_trials_total"] == 9
    trials = ledger.read_trials()
    assert {t["universe"]["fund"] for t in trials} == {"ADX"}
    assert {(t["params"]["window"], t["params"]["entry_z"]) for t in trials} == {
        (w, z) for w in (126, 252, 504) for z in (1.0, 1.5, 2.0)
    }
    assert all(t["signal_path"] == SIGNAL_REL for t in trials)


def test_the_leakage_command_clears_the_registered_signal(cef_env):
    result = runner.invoke(app, ["leakage", "H-0002", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["grid_points"] == 9


def test_n_counts_trials_across_both_theory_packages_in_one_ledger(cef_env):
    write_spec(cef_env, "H-9999")  # the leveraged-ETF package's test hypothesis: 3 grid points
    assert runner.invoke(app, ["run", "H-9999"]).exit_code == 0
    result = runner.invoke(app, ["run", "H-0002", "--json"])
    assert json.loads(result.output)["n_trials_total"] == 12  # 3 + 9, one N
    trials = ledger.read_trials()
    assert [t["n"] for t in trials] == list(range(1, 13))
    assert {t["universe"]["fund"] for t in trials} == {"TQQQ", "ADX"}
    # the judge's inputs carry both packages' trials, so every N-based correction sees all 12
    assert ledger.count_trials() == 12 and ledger.trial_matrix().shape[1] == 12


def test_the_judge_runs_on_a_cef_hypothesis(cef_env):
    assert runner.invoke(app, ["run", "H-0002"]).exit_code == 0
    result = runner.invoke(app, ["judge", "H-0002", "--json"])
    assert result.exit_code == 0, result.output
    verdict = json.loads(result.output)
    assert verdict["train_verdict"] in {"advance", "reject"}
    assert verdict["hypothesis_id"] == "H-0002"


@pytest.mark.parametrize("hypothesis_id", ["H-9999", "H-0002"])
def test_the_same_run_and_judge_entry_points_serve_the_etf_and_the_cef_theory(
    cef_env, hypothesis_id
):
    if hypothesis_id == "H-9999":
        write_spec(cef_env, "H-9999")
    ran = runner.invoke(app, ["run", hypothesis_id, "--json"])
    assert ran.exit_code == 0, ran.output
    judged = runner.invoke(app, ["judge", hypothesis_id, "--json"])
    assert judged.exit_code == 0, judged.output
    verdict = json.loads(judged.output)
    assert verdict["hypothesis_id"] == hypothesis_id
    assert verdict["train_verdict"] in {"advance", "reject"}


@pytest.fixture
def cef_holdout(cef_env, monkeypatch):
    """A disposable key and a synthetic encrypted slice that includes the ADX series."""
    key = Fernet.generate_key()
    idx = pd.bdate_range("2019-10-01", periods=700)
    rng = np.random.default_rng(3)
    nav = pd.Series(20 * np.exp(np.cumsum(rng.normal(0, 0.01, 700))), index=idx)
    quote = nav * (1 + (-0.12 + 0.03 * rng.standard_normal(700)))
    frame = pd.DataFrame(
        {
            "ADX": quote,
            "PX:ADX": quote,
            "NAV:ADX": nav,
            "^VIX": 20.0,
            "FRED:DGS3MO": 2.0,
            "FRED:DFF": 2.0,
        }
    )
    encrypt_holdout(frame, key, cache.holdout_path())
    monkeypatch.setattr(
        judge_runner, "os", SimpleNamespace(environ={"LAB_HOLDOUT_KEY": key.decode()})
    )
    monkeypatch.setattr(
        judge_runner,
        "judge_hypothesis",
        lambda hid, seed=judge_runner.JUDGE_SEED, ctx=None: {
            "hypothesis_id": hid,
            "train_verdict": "advance",
            "thresholds_hash": "test",
            "chosen_trial": ctx.chosen["trial_id"],
        },
    )
    assert runner.invoke(app, ["run", "H-0002"]).exit_code == 0
    return frame


def test_a_cef_hypothesis_is_scored_once_on_the_hold_out(cef_holdout):
    result = judge_runner.holdout_hypothesis("H-0002")
    assert set(result) == {"hypothesis_id", "holdout_verdict", "scored_at"}
    assert [(e["event"], e.get("outcome")) for e in ledger.read_holdout_attempts()] == [
        ("started", None),
        ("finished", result["holdout_verdict"]),
    ]
    report = json.loads((cache.results_dir() / "holdout" / "H-0002.json").read_text())
    assert report["n_obs"] > 0
    with pytest.raises(ledger.HoldoutAlreadyScoredError):
        judge_runner.holdout_hypothesis("H-0002")


def test_the_hold_out_run_hands_the_spec_features_to_the_signal(cef_holdout, monkeypatch):
    ctx = judge_runner.prepare("H-0002", frozen=True)
    seen = {}
    real = judge_runner.run_backtest

    def spy(signal, features, *args, **kwargs):
        seen["columns"] = set(features.columns)
        return real(signal, features, *args, **kwargs)

    monkeypatch.setattr(judge_runner, "run_backtest", spy)
    judge_runner._holdout_run(ctx)(cef_holdout)
    assert {"close", "raw_close", "nav"} <= seen["columns"]
    assert ctx.result.returns.index.max() < cef_holdout.index.min()  # train and slice are apart


def test_a_hold_out_file_without_the_features_fails_loudly(cef_holdout):
    frame = cef_holdout.drop(columns=["NAV:ADX"])
    ctx = judge_runner.prepare("H-0002", frozen=True)
    with pytest.raises(judge_runner.RunError, match="no series 'NAV:ADX'"):
        judge_runner._holdout_run(ctx)(frame)
