"""`lab run` refuses hypotheses that are not pre-registered (SPEC Section 7.2), using throwaway git
repos and a temporary ledger."""

import json

import pytest
from typer.testing import CliRunner

from core.cli import app
from core.ledger import ledger, prereg
from tests.prereg_helpers import SIGNAL_REL, commit_all, git, init_repo, write_spec

runner = CliRunner()


@pytest.fixture
def env(pulled, monkeypatch, tmp_path):
    monkeypatch.setenv("LAB_DATA_DIR", str(pulled["tmp_path"]))
    monkeypatch.setenv("LAB_LEDGER_DIR", str(tmp_path / "ledger"))
    repo = init_repo(tmp_path / "repo")
    monkeypatch.setenv("LAB_HYPOTHESES_DIR", str(repo / "hypotheses"))
    return repo


def refused(reason: str):
    result = runner.invoke(app, ["run", "H-9999"])
    assert result.exit_code == 1, result.output
    assert reason in result.output, result.output
    assert ledger.count_trials() == 0 or "hash" in reason
    return result


def test_a_committed_spec_runs_and_records_its_pre_registration(env):
    write_spec(env)
    commit = git(env, "rev-parse", "HEAD")
    result = runner.invoke(app, ["run", "H-9999", "--json"])
    assert result.exit_code == 0, result.output
    trials = ledger.read_trials()
    assert len(trials) == 3
    for t in trials:
        assert t["git_commit"] == commit
        assert t["spec_path"] == "hypotheses/H-9999_test.yaml" and t["signal_path"] == SIGNAL_REL
        assert len(t["spec_hash"]) == len(t["signal_hash"]) == 64
        assert t["registered_commit_at"].startswith("2019-01-02")


def test_an_untracked_spec_is_refused(env):
    write_spec(env, commit=False)
    refused("is not committed")


def test_a_staged_but_uncommitted_spec_is_refused(env):
    write_spec(env, commit=False)
    git(env, "add", "-A")
    refused("uncommitted changes")


def test_an_edited_spec_is_refused(env):
    path = write_spec(env)
    path.write_text(path.read_text() + "# edited after commit\n")
    refused("uncommitted changes")


def test_an_edited_signal_module_is_refused(env):
    write_spec(env)
    (env / SIGNAL_REL).write_text((env / SIGNAL_REL).read_text() + "\n# tweak\n")
    refused("uncommitted changes")


def test_a_gitignored_spec_is_refused(env):
    (env / ".gitignore").write_text("hypotheses/H-9999_*.yaml\n")
    commit_all(env, "ignore", date="2019-01-01T00:00:00+00:00")
    write_spec(env, commit=False)
    refused("is not committed")


def test_a_commit_dated_after_the_run_is_refused(env):
    write_spec(env, commit=False)
    commit_all(env, "from the future", date="2099-01-01T00:00:00+00:00")
    refused("not before the run time")


def test_a_spec_outside_any_git_repository_is_refused(env, monkeypatch, tmp_path):
    loose = tmp_path / "loose"
    (loose / "hypotheses" / "signals").mkdir(parents=True)
    monkeypatch.setenv("LAB_HYPOTHESES_DIR", str(loose / "hypotheses"))
    write_spec(loose, commit=False)
    (loose / SIGNAL_REL).write_text((env / SIGNAL_REL).read_text())
    refused("not inside a git repository")


def test_a_signal_module_outside_the_spec_repository_is_refused(env, tmp_path):
    other = init_repo(tmp_path / "other")
    write_spec(env, signal_module=str(other / SIGNAL_REL))
    refused("different repositories")


def test_a_spec_committed_after_trials_exist_no_longer_matches_the_ledger(env):
    path = write_spec(env)
    assert runner.invoke(app, ["run", "H-9999"]).exit_code == 0
    path.write_text(path.read_text().replace("test-only", "retuned"))
    commit_all(env, "widen the grid after seeing results", date="2019-02-01T00:00:00+00:00")
    result = refused("spec hash")
    assert "register a new hypothesis" in result.output
    assert ledger.count_trials() == 3


def test_a_signal_changed_after_trials_exist_no_longer_matches_the_ledger(env):
    write_spec(env)
    assert runner.invoke(app, ["run", "H-9999"]).exit_code == 0
    (env / SIGNAL_REL).write_text((env / SIGNAL_REL).read_text() + "\n# tweak\n")
    commit_all(env, "tweak the signal", date="2019-02-01T00:00:00+00:00")
    refused("signal module hash")
    assert ledger.count_trials() == 3


def test_an_unchanged_committed_spec_can_be_rerun(env):
    write_spec(env)
    for expected in (3, 6):
        out = runner.invoke(app, ["run", "H-9999", "--json"]).output
        assert json.loads(out)["n_trials_total"] == expected


def test_other_hypotheses_trials_do_not_block_a_new_spec(env):
    write_spec(env, "H-9998")
    assert runner.invoke(app, ["run", "H-9998"]).exit_code == 0
    write_spec(env, "H-9999")
    assert runner.invoke(app, ["run", "H-9999"]).exit_code == 0
    assert ledger.count_trials() == 6


def test_verify_frozen_rejects_a_file_that_does_not_hash_to_the_ledger_record(env):
    path = write_spec(env)
    assert runner.invoke(app, ["run", "H-9999"]).exit_code == 0
    trial = ledger.read_trials()[0]
    spec_bytes, signal_bytes = prereg.verify_frozen(env, trial)
    assert spec_bytes == path.read_bytes() and signal_bytes == (env / SIGNAL_REL).read_bytes()
    with pytest.raises(prereg.PreregError, match="does not match the hash"):
        prereg.verify_frozen(env, {**trial, "signal_hash": "0" * 64})
    with pytest.raises(prereg.PreregError, match="lacks pre-registration fields"):
        prereg.verify_frozen(env, {k: v for k, v in trial.items() if k != "git_commit"})
