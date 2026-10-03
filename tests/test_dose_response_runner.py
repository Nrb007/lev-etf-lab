"""The leverage-aware caller of the generic dose-response check, on the recorded mini universe."""

import json

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from core import dose_response_runner as runner_module
from core.cli import app
from core.data import cache
from core.data.splits import load_prices
from core.data.synthetic import (
    LEVERAGE_FACTORS,
    daily_returns,
    synthetic_prices,
    synthetic_returns,
)
from core.engine.backtest import ExecutionConfig, daily_risk_free, run_backtest
from core.judge.verdict import TEST_ORDER
from core.ledger import ledger
from tests.fixture_signals import MovingAverageCrossover
from tests.prereg_helpers import init_repo, write_spec

cli = CliRunner()


@pytest.fixture
def lab_env(pulled, monkeypatch, tmp_path):
    monkeypatch.setenv("LAB_DATA_DIR", str(pulled["tmp_path"]))
    monkeypatch.setenv("LAB_LEDGER_DIR", str(tmp_path / "ledger"))
    monkeypatch.setenv("LAB_RESULTS_DIR", str(tmp_path / "results"))
    repo = init_repo(tmp_path / "repo")
    monkeypatch.setenv("LAB_HYPOTHESES_DIR", str(repo / "hypotheses"))
    write_spec(repo)
    assert cli.invoke(app, ["run", "H-9999"]).exit_code == 0
    return tmp_path


def planted(effect_at):
    """Replace the engine-driven effects with a planted dose -> effect map."""
    return lambda ctx, metric="excess_return", factors=LEVERAGE_FACTORS: (
        {float(d): effect_at(d) for d in factors},
        {"window": ["2018-06-01", "2019-09-30"], "underlying": "QQQ"},
    )


def test_effects_are_the_engine_excess_return_on_each_synthetic_variant(lab_env):
    ctx = runner_module.prepare("H-9999")
    effects, meta = runner_module.leverage_effects(ctx)
    assert sorted(effects) == sorted(float(f) for f in LEVERAGE_FACTORS)
    assert meta["underlying"] == "QQQ"

    frame = load_prices(["QQQ", "FRED:DFF", "FRED:DGS3MO"], "train")
    under = daily_returns(frame["QQQ"].dropna())
    for factor in (3, -2):  # one long, one inverse: assemble by hand and compare
        prices = synthetic_prices(synthetic_returns(under, frame["FRED:DFF"], factor))
        fund = daily_returns(prices).dropna()
        features = pd.DataFrame({"close": prices, "underlying": frame["QQQ"].reindex(prices.index)})
        rf = daily_risk_free(frame["FRED:DGS3MO"]).reindex(fund.index)
        result = run_backtest(
            MovingAverageCrossover(ctx.chosen["params"]["window"]),
            features,
            fund,
            rf,
            ExecutionConfig(**ctx.chosen["execution"]),
        )
        expected = result.metrics["cagr"] - result.benchmarks["buy_and_hold"].metrics["cagr"]
        assert effects[float(factor)] == pytest.approx(expected, abs=1e-9)


def test_caller_passes_leverage_factors_as_dose_and_effects_to_the_generic_test(
    lab_env, monkeypatch
):
    calls = []
    real = runner_module.dose_response_test

    def spy(dose, effect, criteria=None):
        calls.append((list(dose), list(effect), criteria))
        return real(dose, effect, criteria)

    monkeypatch.setattr(runner_module, "dose_response_test", spy)
    monkeypatch.setattr(runner_module, "leverage_effects", planted(lambda d: 0.01 * d * abs(d)))
    payload = runner_module.dose_response_hypothesis("H-9999")
    ((dose, effect, criteria),) = calls
    assert dose == [-3.0, -2.0, -1.0, 1.0, 2.0, 3.0]
    assert effect == [-0.09, -0.04, -0.01, 0.01, 0.04, 0.09]
    assert criteria == runner_module.load_thresholds().dose_response
    assert payload["effects"]["-3"] == -0.09 and payload["flag"] == "supported"


@pytest.mark.parametrize(
    "effect_at, flag",
    [
        (lambda d: 0.01 * d * abs(d), "supported"),
        (lambda d: 0.01 * d * d, runner_module.FLAG_NOT_SUPPORTED),  # works on 3x, no reversal
        (lambda d: 0.05 * d, runner_module.FLAG_NOT_SUPPORTED),  # works on 3x, linear
        (lambda d: -0.01 * d * d, "not applicable: no positive effect at the spec's own leverage"),
        (lambda d: 0.0, "not evaluable"),
    ],
)
def test_flag_depends_on_status_and_on_whether_the_signal_works_at_its_own_leverage(
    lab_env, monkeypatch, effect_at, flag
):
    monkeypatch.setattr(runner_module, "leverage_effects", planted(effect_at))
    assert runner_module.dose_response_hypothesis("H-9999")["flag"] == flag


def test_result_file_records_inputs_criteria_and_that_no_trials_were_added(lab_env):
    before = ledger.count_trials()
    payload = runner_module.dose_response_hypothesis("H-9999")
    saved = json.loads((lab_env / "results" / "H-9999" / "dose_response.json").read_text())
    assert saved == json.loads(json.dumps(payload))
    assert saved["chosen_trial"] and saved["metric"] == "excess_return"
    assert saved["spec_leverage"] == 3.0 and set(saved["dose_response"]["tests"]) == {
        "scaling",
        "sign_reversal",
        "fit",
    }
    assert ledger.count_trials() == before  # diagnostics, not trials
    assert runner_module.dose_response_hypothesis("H-9999") == payload  # deterministic


def test_excess_sharpe_metric_and_unknown_metric(lab_env):
    ctx = runner_module.prepare("H-9999")
    sharpe, _ = runner_module.leverage_effects(ctx, "excess_sharpe")
    returns, _ = runner_module.leverage_effects(ctx, "excess_return")
    assert sharpe != returns
    with pytest.raises(runner_module.RunError, match="unknown metric"):
        runner_module.leverage_effects(ctx, "sortino")


def test_cli_runs_the_check_and_judge_battery_does_not_include_it(lab_env):
    result = cli.invoke(app, ["dose-response", "H-9999", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["hypothesis_id"] == "H-9999"
    judged = json.loads(cli.invoke(app, ["judge", "H-9999", "--json"]).output)
    assert "dose_response" not in judged["tests"] and "dose_response" not in TEST_ORDER
    text = cli.invoke(app, ["dose-response", "H-9999"]).output
    assert text.startswith("H-9999: ") and "excess_return" in text


def test_cli_errors_cleanly(lab_env):
    assert cli.invoke(app, ["dose-response", "H-1234"]).exit_code == 1
    result = cli.invoke(app, ["dose-response", "H-9999", "--metric", "nope"])
    assert result.exit_code == 1 and "unknown metric" in result.output


def test_synthetic_variants_do_not_depend_on_the_hypotheses_own_research_universe(lab_env):
    # H-9999 is a "real" TQQQ spec; its effects must still come from synthetic QQQ variants.
    assert "SYNTH" not in "".join(p.name for p in cache.cache_dir().iterdir())
    effects, _ = runner_module.leverage_effects(runner_module.prepare("H-9999"))
    assert all(np.isfinite(v) for v in effects.values())
