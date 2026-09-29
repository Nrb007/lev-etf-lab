import json
from pathlib import Path

import pandas as pd
import pytest
import yaml
from typer.testing import CliRunner

from core.cli import app
from core.ledger import ledger

runner = CliRunner()
SIGNAL_MODULE = Path(__file__).parent / "fixtures" / "hypotheses" / "h9999_ma_signal.py"


def write_spec(directory: Path, hid="H-9999", params=None):
    directory.mkdir(parents=True, exist_ok=True)
    spec = {
        "id": hid,
        "title": "test-only moving average",
        "universe": {"fund": "TQQQ", "underlying": "QQQ", "research_universe": "real"},
        "signal_module": str(SIGNAL_MODULE),
        "params": params or {"window": {"values": [5, 10, 20]}},
    }
    (directory / f"{hid}_test.yaml").write_text(yaml.safe_dump(spec))


@pytest.fixture
def lab_env(pulled, monkeypatch, tmp_path):
    monkeypatch.setenv("LAB_DATA_DIR", str(pulled["tmp_path"]))
    monkeypatch.setenv("LAB_LEDGER_DIR", str(tmp_path / "ledger"))
    monkeypatch.setenv("LAB_HYPOTHESES_DIR", str(tmp_path / "hypotheses"))
    write_spec(tmp_path / "hypotheses")
    return tmp_path


def test_run_records_every_grid_point(lab_env):
    result = runner.invoke(app, ["run", "H-9999", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["n_grid_points"] == 3
    assert payload["n_trials_total"] == 3
    assert set(payload["benchmarks"]) == {"buy_and_hold", "half_cash"}

    trials = ledger.read_trials()
    assert [t["n"] for t in trials] == [1, 2, 3]
    assert [t["params"]["window"] for t in trials] == [5, 10, 20]
    for t in trials:
        assert t["hypothesis_id"] == "H-9999"
        assert t["universe"]["research_universe"] == "real"
        assert {"spec_hash", "thresholds_hash", "timestamp", "metrics"} <= set(t)
        stored = pd.read_parquet(lab_env / "ledger" / t["returns_path"])
        assert len(stored) > 100 and stored["return"].notna().all()
    assert ledger.trial_matrix().shape[1] == 3


def test_reruns_keep_counting(lab_env):
    for expected in (3, 6):
        result = runner.invoke(app, ["run", "H-9999", "--json"])
        assert json.loads(result.output)["n_trials_total"] == expected
    assert ledger.count_trials() == 6


def test_trial_lines_are_only_ever_appended(lab_env):
    runner.invoke(app, ["run", "H-9999"])
    before = (lab_env / "ledger" / "trials.jsonl").read_text()
    runner.invoke(app, ["run", "H-9999"])
    assert (lab_env / "ledger" / "trials.jsonl").read_text().startswith(before)


def test_leaky_signal_aborts_the_run_and_records_nothing_for_it(lab_env):
    write_spec(
        lab_env / "hypotheses", "H-9998", {"window": {"values": [5]}, "leaky": {"values": [True]}}
    )
    result = runner.invoke(app, ["run", "H-9998"])
    assert result.exit_code == 1
    assert "lookahead" in result.output or "leakage" in result.output
    assert ledger.count_trials() == 0


def test_later_grid_point_failure_keeps_earlier_points_recorded(lab_env):
    write_spec(
        lab_env / "hypotheses",
        "H-9997",
        {"window": {"values": [5]}, "leaky": {"values": [False, True]}},
    )
    result = runner.invoke(app, ["run", "H-9997"])
    assert result.exit_code == 1
    trials = ledger.read_trials()
    assert [(t["hypothesis_id"], t["n"]) for t in trials] == [("H-9997", 1)]
    assert trials[0]["params"]["leaky"] is False
    assert ledger.count_trials() == 1
    assert ledger.trial_matrix().shape[1] == 1


def test_concurrent_appends_get_distinct_trial_numbers(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setenv("LAB_LEDGER_DIR", str(tmp_path / "ledger"))
    series = pd.Series([0.01, 0.02], index=pd.to_datetime(["2020-01-02", "2020-01-03"]))

    def add(i):
        return ledger.append_trial({"hypothesis_id": "H-0001", "params": {"i": i}}, series)["n"]

    with ThreadPoolExecutor(8) as pool:
        ns = list(pool.map(add, range(24)))
    assert sorted(ns) == list(range(1, 25))
    assert ledger.count_trials() == 24
    assert ledger.trial_matrix().shape[1] == 24


def test_unknown_hypothesis_fails_cleanly(lab_env):
    result = runner.invoke(app, ["run", "H-0042"])
    assert result.exit_code == 1
    assert "no spec file" in result.output


def test_backtest_uses_only_train_data(lab_env):
    runner.invoke(app, ["run", "H-9999"])
    from core.data.splits import split_dates

    limit = split_dates().embargo_start
    for t in ledger.read_trials():
        assert pd.Timestamp(t["window"][1]) < limit
