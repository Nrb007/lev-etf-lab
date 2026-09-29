"""`lab` entry point. Every command is a stub until its own milestone lands."""

from __future__ import annotations

from typing import Annotated

import typer

from core.config import load_lab_config, load_thresholds

app = typer.Typer(help="lev-etf-lab command line.", no_args_is_help=True)
data_app = typer.Typer(help="Data layer commands.", no_args_is_help=True)
ledger_app = typer.Typer(help="Ledger commands.", no_args_is_help=True)
dashboard_app = typer.Typer(help="Dashboard commands.", no_args_is_help=True)
app.add_typer(data_app, name="data")
app.add_typer(ledger_app, name="ledger")
app.add_typer(dashboard_app, name="dashboard")


@app.callback()
def _main() -> None:
    # Fail loudly at startup if either config file is invalid.
    load_lab_config()
    load_thresholds()


def _not_implemented(command: str) -> None:
    typer.echo(f"lab {command}: not yet implemented", err=True)
    raise typer.Exit(code=1)


@data_app.command("pull")
def data_pull(
    refresh: Annotated[bool, typer.Option("--refresh", help="Re-fetch cached data.")] = False,
) -> None:
    """Fetch and cache market data."""
    _not_implemented("data pull")


@data_app.command("validate")
def data_validate() -> None:
    """Run data quality checks."""
    _not_implemented("data validate")


@data_app.command("synth")
def data_synth(
    fund: Annotated[str, typer.Option("--fund", help="Fund ticker, e.g. TQQQ.")] = "",
    leverage: Annotated[float, typer.Option("--leverage", help="Leverage factor.")] = 3,
) -> None:
    """Build a synthetic leveraged fund."""
    _not_implemented("data synth")


@app.command("run")
def run(hypothesis_id: Annotated[str, typer.Argument(metavar="H-XXXX")]) -> None:
    """Run a pre-registered hypothesis grid."""
    _not_implemented("run")


@app.command("judge")
def judge(hypothesis_id: Annotated[str, typer.Argument(metavar="H-XXXX")]) -> None:
    """Judge a hypothesis on the train split."""
    _not_implemented("judge")


@app.command("holdout")
def holdout(hypothesis_id: Annotated[str, typer.Argument(metavar="H-XXXX")]) -> None:
    """Score a hypothesis once on the hold-out (human-run)."""
    _not_implemented("holdout")


@ledger_app.command("summary")
def ledger_summary() -> None:
    """Summarize the trial ledger."""
    _not_implemented("ledger summary")


@app.command("report")
def report(hypothesis_id: Annotated[str, typer.Argument(metavar="H-XXXX")]) -> None:
    """Write up a hypothesis result."""
    _not_implemented("report")


@dashboard_app.command("build")
def dashboard_build() -> None:
    """Build the static dashboard."""
    _not_implemented("dashboard build")
