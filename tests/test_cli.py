import json

import pytest
from typer.testing import CliRunner

from core.cli import app
from core.data.loaders import FetchError

runner = CliRunner()

COMMANDS = [
    ["data", "pull"],
    ["data", "validate"],
    ["data", "synth"],
    ["run"],
    ["judge"],
    ["holdout"],
    ["ledger", "summary"],
    ["report"],
    ["dashboard", "build"],
]


def test_top_level_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ["data", "run", "judge", "holdout", "ledger", "report", "dashboard"]:
        assert name in result.output


@pytest.mark.parametrize("cmd", COMMANDS, ids=" ".join)
def test_subcommand_help(cmd):
    result = runner.invoke(app, [*cmd, "--help"])
    assert result.exit_code == 0
    assert cmd[-1] in result.output


STUBS = [cmd for cmd in COMMANDS if cmd[0] != "data" and cmd != ["run"]]


@pytest.mark.parametrize("cmd", STUBS, ids=" ".join)
def test_stub_exits_nonzero(cmd):
    args = [*cmd, "H-0001"] if cmd[0] in {"run", "judge", "holdout", "report"} else cmd
    result = runner.invoke(app, args)
    assert result.exit_code != 0
    assert "not yet implemented" in result.output


@pytest.fixture
def data_env(pulled, monkeypatch):
    """Point the CLI at the fixture-backed cache and a temporary results dir."""
    tmp = pulled["tmp_path"]
    monkeypatch.setenv("LAB_DATA_DIR", str(tmp))
    monkeypatch.setenv("LAB_RESULTS_DIR", str(tmp / "results"))
    return tmp


def test_data_validate_writes_report(data_env):
    result = runner.invoke(app, ["data", "validate", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["passed"] is True
    assert (data_env / "results" / "data_quality.json").exists()


def test_data_validate_fails_on_empty_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("LAB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LAB_RESULTS_DIR", str(tmp_path / "results"))
    result = runner.invoke(app, ["data", "validate"])
    assert result.exit_code == 1
    assert "no cached series" in result.output


def test_data_synth_builds_and_validates(data_env):
    result = runner.invoke(app, ["data", "synth", "--fund", "TQQQ", "--leverage", "3", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["synthetic"]["research_universe"] == "synthetic_long"
    assert 0.99 < payload["validation"]["daily_return_correlation"] <= 1
    assert "TQQQ_3x" in json.loads((data_env / "results" / "data_validation.json").read_text())
    assert (data_env / "cache" / "SYNTH_TQQQ_3x.parquet").exists()


def test_data_synth_requires_fund_and_known_underlying(data_env):
    assert runner.invoke(app, ["data", "synth"]).exit_code == 1
    result = runner.invoke(app, ["data", "synth", "--fund", "TECL"])
    assert result.exit_code == 1
    assert "TECL" in result.output


def test_data_pull_reports_fetch_errors_and_success(monkeypatch):
    def failing(**_):
        raise FetchError("QQQ: boom")

    monkeypatch.setattr("core.cli.pull", failing)
    result = runner.invoke(app, ["data", "pull"])
    assert result.exit_code == 1
    assert "boom" in result.output

    monkeypatch.setattr(
        "core.cli.pull",
        lambda **_: {"series": {"QQQ": "fetched"}, "holdout_written": False, "fetched_at": "t"},
    )
    ok = runner.invoke(app, ["data", "pull", "--json"])
    assert ok.exit_code == 0
    assert json.loads(ok.output)["series"] == {"QQQ": "fetched"}
