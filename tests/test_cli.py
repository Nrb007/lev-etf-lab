import pytest
from typer.testing import CliRunner

from core.cli import app

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


@pytest.mark.parametrize("cmd", COMMANDS, ids=" ".join)
def test_stub_exits_nonzero(cmd):
    args = [*cmd, "H-0001"] if cmd[0] in {"run", "judge", "holdout", "report"} else cmd
    result = runner.invoke(app, args)
    assert result.exit_code != 0
    assert "not yet implemented" in result.output
