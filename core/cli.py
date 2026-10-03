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
from core.dashboard_build import BuildError
from core.dashboard_build import build as build_dashboard
from core.dashboard_export import export_all
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
from core.data.variants import build_variants
from core.dose_response_runner import METRICS, dose_response_hypothesis
from core.engine.backtest import BacktestError, LeakageError
from core.engine.signal_api import SignalError
from core.judge.common import JudgeError
from core.judge_runner import holdout_hypothesis, judge_hypothesis
from core.ledger.ledger import LedgerError
from core.ledger.summary import format_summary, summarize
from core.runner import RunError, check_leakage_for, run_hypothesis

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


_JUDGE_ERRORS = (
    RunError,
    JudgeError,
    BacktestError,
    LeakageError,
    SignalError,
    LedgerError,
    CacheMissError,
    CacheCorruptError,
    ValueError,
)

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


@data_app.command("variants")
def data_variants(as_json: JsonOption = False) -> None:
    """Cache synthetic leverage/inverse variants of each underlying; check against real funds."""
    try:
        result = build_variants()
    except (ValueError, CacheMissError, CacheCorruptError) as exc:
        typer.echo(f"lab data variants: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    lines = [f"cached {len(result['variants'])} synthetic variants"]
    for v in result["validations"]:
        if "skipped" in v:
            lines.append(f"  {v['fund']} {v['leverage']:g}x: skipped ({v['skipped']})")
        else:
            lines.append(
                f"  {v['fund']} {v['leverage']:g}x vs synthetic {v['underlying']}: correlation "
                f"{v['daily_return_correlation']:.5f} (target met: {v['correlation_target_met']})"
            )
    _emit(result, as_json, "\n".join(lines))


@app.command("run")
def run(
    hypothesis_id: Annotated[str, typer.Argument(metavar="H-XXXX")],
    as_json: JsonOption = False,
) -> None:
    """Backtest a hypothesis's parameter grid on the train split and record every trial."""
    try:
        result = run_hypothesis(hypothesis_id)
    except (
        RunError,
        LedgerError,
        BacktestError,
        LeakageError,
        SignalError,
        CacheMissError,
        CacheCorruptError,
        ValueError,
    ) as exc:
        typer.echo(f"lab run: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    _emit(
        result,
        as_json,
        f"{hypothesis_id}: {result['n_grid_points']} grid points recorded; "
        f"N = {result['n_trials_total']}",
    )


@app.command("leakage")
def leakage(
    hypothesis_id: Annotated[str, typer.Argument(metavar="H-XXXX")],
    seed: Annotated[int | None, typer.Option("--seed", help="Override the fixed seed.")] = None,
    as_json: JsonOption = False,
) -> None:
    """Run the leakage self-test on a spec's signal (read-only; records no trials)."""
    try:
        result = check_leakage_for(hypothesis_id, seed=seed)
    except _JUDGE_ERRORS as exc:
        typer.echo(f"lab leakage: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    _emit(
        result,
        as_json,
        f"{hypothesis_id}: no leakage across {result['grid_points']} grid points "
        f"({result['dates_checked_per_point']} truncation dates each)",
    )


@app.command("judge")
def judge(
    hypothesis_id: Annotated[str, typer.Argument(metavar="H-XXXX")],
    as_json: JsonOption = False,
) -> None:
    """Run the train-split test battery and verdict on a hypothesis's recorded trials."""
    try:
        verdict = judge_hypothesis(hypothesis_id)
    except _JUDGE_ERRORS as exc:
        typer.echo(f"lab judge: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    reasons = ", ".join(verdict["reasons"]) or "none"
    _emit(
        verdict,
        as_json,
        f"{hypothesis_id}: {verdict['train_verdict']} (N = {verdict['n_trials']}; "
        f"failing: {reasons})",
    )


@app.command("dose-response")
def dose_response(
    hypothesis_id: Annotated[str, typer.Argument(metavar="H-XXXX")],
    metric: Annotated[
        str, typer.Option("--metric", help=f"Effect per leverage: {' or '.join(METRICS)}.")
    ] = "excess_return",
    as_json: JsonOption = False,
) -> None:
    """Optional vol-drag check: does the chosen signal's effect scale with L^2 and flip for -L?

    Not part of `lab judge`. Re-runs the chosen point on synthetic 1x/2x/3x/-1x/-2x/-3x funds
    (diagnostics, not ledger trials) and writes results/<id>/dose_response.json.
    """
    try:
        result = dose_response_hypothesis(hypothesis_id, metric)
    except _JUDGE_ERRORS as exc:
        typer.echo(f"lab dose-response: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    effects = ", ".join(f"{d}x: {v:+.4f}" for d, v in result["effects"].items())
    _emit(
        result,
        as_json,
        f"{hypothesis_id}: {result['flag']} ({result['metric']}: {effects})",
    )


@app.command("holdout")
def holdout(
    hypothesis_id: Annotated[str, typer.Argument(metavar="H-XXXX")],
    as_json: JsonOption = False,
) -> None:
    """Score a hypothesis on the hold-out (human-run). Prints only pass/fail and a timestamp."""
    try:
        result = holdout_hypothesis(hypothesis_id)
    except _JUDGE_ERRORS as exc:
        typer.echo(f"lab holdout: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    _emit(
        result,
        as_json,
        f"{hypothesis_id}: hold-out {result['holdout_verdict']} at {result['scored_at']}",
    )


@ledger_app.command("summary")
def ledger_summary(as_json: JsonOption = False) -> None:
    """Trial count N and train-split verdict state per hypothesis (never hold-out results)."""
    try:
        summary = summarize()
    except (LedgerError, ValueError) as exc:
        typer.echo(f"lab ledger summary: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    _emit(summary, as_json, format_summary(summary))


@app.command("report")
def report(hypothesis_id: Annotated[str, typer.Argument(metavar="H-XXXX")]) -> None:
    """Write up a hypothesis result."""
    _not_implemented("report")


@dashboard_app.command("export")
def dashboard_export_cmd(as_json: JsonOption = False) -> None:
    """Write results/<id>/detail.json and results/index.json from the ledger and verdicts."""
    try:
        index = export_all()
    except _JUDGE_ERRORS as exc:
        typer.echo(f"lab dashboard export: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    f = index["funnel"]
    _emit(
        index,
        as_json,
        f"exported {f['proposed']} hypotheses (N = {index['n_trials']}): "
        f"{f['passed_judge']} advanced, {f['proposed'] - f['passed_judge']} rejected",
    )


@dashboard_app.command("build")
def dashboard_build_cmd(
    skip_export: Annotated[
        bool,
        typer.Option(
            "--skip-export", help="Use the committed results/*.json instead of re-exporting."
        ),
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Export, then build the static dashboard into dashboard/dist/ (needs Node.js)."""
    try:
        result = build_dashboard(skip_export=skip_export)
    except (BuildError, *_JUDGE_ERRORS) as exc:
        typer.echo(f"lab dashboard build: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    _emit(result, as_json, f"built {result['output_dir']} ({len(result['published'])} data files)")
