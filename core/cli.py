"""`lab` entry point. Commands not yet implemented are stubs until their milestone lands."""

from __future__ import annotations

import json
import logging
import os
import sys
from collections import Counter
from typing import Annotated

import typer

from core.config import load_lab_config, load_thresholds
from core.data import cache
from core.data.cache import CacheCorruptError, CacheMissError
from core.data.loaders import FetchError, pull
from core.data.splits import load_prices
from core.data.synthetic import (
    DEFAULT_EXPENSE_RATIO,
    DEFAULT_FINANCING_SPREAD,
    daily_returns,
    research_prices,
    validate_against_real,
)
from core.data.validate import DataQualityError, run_validation

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


def _emit(payload: dict, as_json: bool, summary: str) -> None:
    typer.echo(json.dumps(payload, indent=2, sort_keys=True) if as_json else summary)


JsonOption = Annotated[bool, typer.Option("--json", help="Print machine-readable output.")]


@data_app.command("pull")
def data_pull(
    refresh: Annotated[bool, typer.Option("--refresh", help="Re-fetch cached data.")] = False,
    as_json: JsonOption = False,
) -> None:
    """Fetch and cache market data (live network; human-run)."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    try:
        result = pull(refresh=refresh, holdout_key=os.environ.get("LAB_HOLDOUT_KEY"))
    except FetchError as exc:
        typer.echo(f"lab data pull: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    counts = Counter(result["series"].values())
    _emit(result, as_json, f"pulled: {dict(counts)}; holdout_written={result['holdout_written']}")


@data_app.command("validate")
def data_validate(as_json: JsonOption = False) -> None:
    """Run data quality checks on the cache and write results/data_quality.json."""
    try:
        report = run_validation()
    except (DataQualityError, CacheMissError, CacheCorruptError) as exc:
        typer.echo(f"lab data validate: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    _emit(report, as_json, f"data quality passed ({report['warning_count']} warnings)")


@data_app.command("synth")
def data_synth(
    fund: Annotated[str, typer.Option("--fund", help="Fund ticker, e.g. TQQQ.")] = "",
    leverage: Annotated[float, typer.Option("--leverage", help="Leverage factor.")] = 3,
    underlying: Annotated[
        str | None, typer.Option("--underlying", help="Override the default underlying.")
    ] = None,
    financing_spread: Annotated[
        float, typer.Option("--financing-spread", help="Annual spread over DFF.")
    ] = DEFAULT_FINANCING_SPREAD,
    expense_ratio: Annotated[
        float, typer.Option("--expense-ratio", help="Annual expense ratio.")
    ] = DEFAULT_EXPENSE_RATIO,
    as_json: JsonOption = False,
) -> None:
    """Build a synthetic leveraged fund and validate it against the real fund."""
    if not fund:
        typer.echo("lab data synth: --fund is required", err=True)
        raise typer.Exit(code=1)
    try:
        prices, meta = research_prices(
            fund,
            "synthetic_long",
            leverage=leverage,
            underlying=underlying,
            financing_spread=financing_spread,
            expense_ratio=expense_ratio,
        )
        directory = cache.cache_dir()
        cache.write_series(
            directory,
            f"SYNTH:{fund}:{leverage:g}x",
            prices,
            {**meta, "source": "core.data.synthetic", "fetch_time": None},
        )
        summary = f"synthetic {fund} {leverage:g}x: {len(prices)} rows"
        payload = {"synthetic": meta | {"rows": len(prices)}}
        if cache.has_series(directory, fund):
            result = validate_against_real(
                daily_returns(prices), load_prices(fund, "train")[fund], meta=meta
            )
            payload["validation"] = result
            summary += (
                f"; correlation vs real {fund}: {result['daily_return_correlation']:.5f}"
                f" (target met: {result['correlation_target_met']})"
            )
    except (ValueError, CacheMissError, CacheCorruptError) as exc:
        typer.echo(f"lab data synth: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    _emit(payload, as_json, summary)


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
