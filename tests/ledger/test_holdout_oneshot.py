"""Hold-out one-shot guarantee (SPEC Section 6.3): one attempt per hypothesis, recorded in the
ledger, scored with the signal frozen at its pre-registration commit.

Uses a disposable key generated inline (never ``LAB_HOLDOUT_KEY``) and a synthetic hold-out slice.
The train verdict is stubbed to ``advance`` because the mini universe cannot earn one; everything
downstream of that gate is the real code path.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pandas as pd
import pytest
from cryptography.fernet import Fernet
from typer.testing import CliRunner

from core import judge_runner
from core.cli import app
from core.data import cache
from core.data.splits import encrypt_holdout
from core.ledger import ledger
from core.runner import RunError
from tests.prereg_helpers import SIGNAL_REL, commit_all, init_repo, write_spec

runner = CliRunner()


@pytest.fixture
def env(pulled, monkeypatch, tmp_path):
    monkeypatch.setenv("LAB_DATA_DIR", str(pulled["tmp_path"]))
    monkeypatch.setenv("LAB_LEDGER_DIR", str(tmp_path / "ledger"))
    monkeypatch.setenv("LAB_RESULTS_DIR", str(tmp_path / "results"))
    repo = init_repo(tmp_path / "repo")
    monkeypatch.setenv("LAB_HYPOTHESES_DIR", str(repo / "hypotheses"))
    write_spec(repo)
    assert runner.invoke(app, ["run", "H-9999"]).exit_code == 0
    return repo


@pytest.fixture
def holdout(env, monkeypatch):
    """A disposable key and an encrypted synthetic slice at the data dir's hold-out path."""
    key = Fernet.generate_key()
    idx = pd.bdate_range("2019-10-01", periods=120)
    price = pd.Series(range(120), index=idx, dtype="float64") * 0.5 + 100
    frame = pd.DataFrame(
        {"TQQQ": price, "QQQ": price / 3, "^VIX": 20.0, "FRED:DGS3MO": 2.0, "FRED:DFF": 2.0}
    )
    encrypt_holdout(frame, key, cache.holdout_path())
    monkeypatch.setattr(
        judge_runner, "os", SimpleNamespace(environ={"LAB_HOLDOUT_KEY": key.decode()})
    )
    return key


@pytest.fixture
def advance(monkeypatch):
    real = judge_runner.judge_hypothesis

    def stub(hypothesis_id, seed=judge_runner.JUDGE_SEED, ctx=None):
        return {**real(hypothesis_id, seed, ctx), "train_verdict": "advance", "reasons": []}

    monkeypatch.setattr(judge_runner, "judge_hypothesis", stub)


def events():
    return [(e["event"], e.get("outcome")) for e in ledger.read_holdout_attempts()]


def test_the_first_attempt_is_scored_and_recorded_and_a_second_is_refused(env, holdout, advance):
    first = judge_runner.holdout_hypothesis("H-9999")
    assert set(first) == {"hypothesis_id", "holdout_verdict", "scored_at"}
    assert events() == [("started", None), ("finished", first["holdout_verdict"])]
    started = ledger.read_holdout_attempts()[0]
    chosen = judge_runner.choose_trial(ledger.read_trials())
    assert started["git_commit"] == chosen["git_commit"] and started["trial_id"]

    with pytest.raises(ledger.HoldoutAlreadyScoredError, match="one attempt"):
        judge_runner.holdout_hypothesis("H-9999")
    assert len(ledger.read_holdout_attempts()) == 2  # the refusal wrote nothing


def test_the_cli_refuses_a_second_attempt_and_prints_only_pass_or_fail(env, holdout, advance):
    ok = runner.invoke(app, ["holdout", "H-9999", "--json"])
    assert ok.exit_code == 0, ok.output
    assert set(json.loads(ok.output)) == {"hypothesis_id", "holdout_verdict", "scored_at"}
    again = runner.invoke(app, ["holdout", "H-9999"])
    assert again.exit_code == 1 and "already been scored" in again.output


def test_a_rejected_hypothesis_does_not_use_up_its_attempt(env, holdout):
    with pytest.raises(RunError, match="reject"):
        judge_runner.holdout_hypothesis("H-9999")  # 3 trials: the real judge rejects
    assert ledger.read_holdout_attempts() == []


def test_a_wrong_key_does_not_use_up_the_attempt(env, holdout, advance, monkeypatch):
    wrong = SimpleNamespace(environ={"LAB_HOLDOUT_KEY": Fernet.generate_key().decode()})
    monkeypatch.setattr(judge_runner, "os", wrong)
    with pytest.raises(Exception):  # noqa: B017 - cryptography's InvalidToken
        judge_runner.holdout_hypothesis("H-9999")
    assert ledger.read_holdout_attempts() == []


def test_a_crash_after_decryption_still_uses_the_attempt(env, holdout, advance, monkeypatch):
    def boom(ctx):
        def run(frame):
            raise RuntimeError("signal blew up on the slice")

        return run

    monkeypatch.setattr(judge_runner, "_holdout_run", boom)
    with pytest.raises(RuntimeError, match="blew up"):
        judge_runner.holdout_hypothesis("H-9999")
    assert events() == [("started", None), ("finished", "error")]
    with pytest.raises(ledger.HoldoutAlreadyScoredError):  # the attempt is spent
        judge_runner.holdout_hypothesis("H-9999")


def test_missing_key_is_refused_before_anything_is_recorded(env, monkeypatch):
    monkeypatch.delenv("LAB_HOLDOUT_KEY", raising=False)
    result = runner.invoke(app, ["holdout", "H-9999"])
    assert result.exit_code == 1 and "LAB_HOLDOUT_KEY" in result.output
    assert ledger.read_holdout_attempts() == []


def test_attempts_are_tracked_per_hypothesis(env):
    ledger.reserve_holdout_attempt({"hypothesis_id": "H-0001"})
    ledger.reserve_holdout_attempt({"hypothesis_id": "H-0002"})
    with pytest.raises(ledger.HoldoutAlreadyScoredError):
        ledger.reserve_holdout_attempt({"hypothesis_id": "H-0001"})
    assert ledger.holdout_attempted("H-0001") and not ledger.holdout_attempted("H-0003")


def test_concurrent_attempts_have_exactly_one_winner(env):
    def attempt(_):
        try:
            ledger.reserve_holdout_attempt({"hypothesis_id": "H-0007"})
            return True
        except ledger.HoldoutAlreadyScoredError:
            return False

    with ThreadPoolExecutor(8) as pool:
        wins = list(pool.map(attempt, range(16)))
    assert sum(wins) == 1
    assert len(ledger.read_holdout_attempts()) == 1


def test_attempt_log_is_append_only_across_events(env):
    ledger.reserve_holdout_attempt({"hypothesis_id": "H-0001"})
    before = ledger.holdout_attempts_path().read_text()
    ledger.record_holdout_outcome("H-0001", "pass")
    ledger.verify_append_only(before, ledger.holdout_attempts_path().read_text())


def test_the_frozen_signal_comes_from_the_commit_not_the_working_tree(env):
    """After the trials, the working-tree signal is broken and even re-committed: the frozen
    context still runs the pre-registered code."""
    signal = env / SIGNAL_REL
    original = signal.read_text()
    signal.write_text("raise RuntimeError('working tree signal was loaded')\n")
    with pytest.raises(RuntimeError, match="working tree signal"):
        judge_runner.prepare("H-9999")  # not frozen: reads the working tree
    ctx = judge_runner.prepare("H-9999", frozen=True)
    assert ctx.factory(window=5).name == "ma_cross_5"
    commit_all(env, "break the signal after the fact", date="2019-03-01T00:00:00+00:00")
    assert judge_runner.prepare("H-9999", frozen=True).chosen == ctx.chosen
    assert original != signal.read_text()
