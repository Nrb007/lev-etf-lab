import numpy as np
import pandas as pd
import pytest

from core.engine.backtest import (
    LEAKAGE_K,
    BacktestError,
    ExecutionConfig,
    LeakageError,
    apply_position_limits,
    check_leakage,
    daily_risk_free,
    run_backtest,
)
from core.engine.signal_api import Signal, SignalError, compute_positions
from tests.fixture_signals import (
    ConstantSignal,
    FullSampleZScore,
    MovingAverageCrossover,
    ScriptedSignal,
    TomorrowPeek,
)

RF = 0.0001  # daily


@pytest.fixture
def market():
    """250 sessions of noisy prices; features cover one extra leading day, like real data."""
    rng = np.random.default_rng(7)
    index = pd.bdate_range("2020-01-01", periods=251)
    prices = pd.Series(100 * np.cumprod(1 + rng.normal(0.0005, 0.02, 251)), index=index)
    features = pd.DataFrame({"close": prices})
    returns = prices.pct_change().dropna()
    rf = pd.Series(RF, index=returns.index)
    return features, returns, rf


def test_position_is_applied_to_the_next_days_return(market):
    features, returns, rf = market
    day = features.index[100]
    scripted = pd.Series(0.0, index=features.index)
    scripted.loc[day] = 1.0  # decided at the close of `day`
    result = run_backtest(
        ScriptedSignal(scripted), features, returns, rf, ExecutionConfig(cost_bps=0)
    )
    nxt = features.index[101]
    assert result.daily.loc[nxt, "position"] == 1.0
    assert result.daily.loc[day, "position"] == 0.0
    assert result.daily.loc[nxt, "return"] == pytest.approx(returns.loc[nxt])
    assert result.daily.loc[day, "return"] == pytest.approx(RF)  # flat: earns cash, not the return
    assert result.daily["position"].sum() == 1.0


def test_first_return_uses_the_position_from_the_prior_close(market):
    features, returns, rf = market
    result = run_backtest(ConstantSignal(1.0), features, returns, rf, ExecutionConfig(cost_bps=0))
    assert result.returns.iloc[0] == pytest.approx(returns.iloc[0])


def test_same_day_information_cannot_capture_the_same_day_return(market):
    """A signal that reads today's close (allowed) still earns tomorrow's return, not today's."""
    features, returns, rf = market
    up_today = (features["close"].pct_change() > 0).astype(float)
    result = run_backtest(
        ScriptedSignal(up_today), features, returns, rf, ExecutionConfig(cost_bps=0)
    )
    expected = up_today.shift(1).reindex(returns.index).fillna(0.0)
    expected = expected * returns + (1 - expected) * rf
    pd.testing.assert_series_equal(result.returns, expected, check_names=False)


def test_flat_signal_earns_the_risk_free_rate(market):
    features, returns, rf = market
    result = run_backtest(ConstantSignal(0.0), features, returns, rf)
    assert (result.returns == RF).all()
    assert result.metrics["time_in_market"] == 0.0
    assert result.metrics["total_cost"] == 0.0


def test_costs_follow_turnover(market):
    features, returns, rf = market
    result = run_backtest(ConstantSignal(1.0), features, returns, rf, ExecutionConfig(cost_bps=10))
    assert result.daily["turnover"].iloc[0] == 1.0  # entering from flat
    assert result.daily["turnover"].iloc[1:].sum() == 0.0
    assert result.metrics["total_cost"] == pytest.approx(0.001)


def test_benchmarks_are_computed_alongside(market):
    features, returns, rf = market
    cfg = ExecutionConfig(cost_bps=0)
    result = run_backtest(MovingAverageCrossover(10), features, returns, rf, cfg)
    assert set(result.benchmarks) == {"buy_and_hold", "half_cash"}
    bh, half = result.benchmarks["buy_and_hold"], result.benchmarks["half_cash"]
    pd.testing.assert_series_equal(bh.returns, returns, check_names=False)
    pd.testing.assert_series_equal(half.returns, 0.5 * returns + 0.5 * rf, check_names=False)
    for bench in (bh, half):
        assert {"cagr", "sharpe", "max_drawdown", "time_in_market"} <= set(bench.metrics)
    assert bh.metrics["time_in_market"] == 1.0
    # Benchmarks pay the same entry cost as the strategy when costs are on.
    costly = run_backtest(ConstantSignal(1.0), features, returns, rf, ExecutionConfig(cost_bps=5))
    assert costly.benchmarks["buy_and_hold"].metrics["total_cost"] == pytest.approx(0.0005)


def test_result_carries_every_section_5_3_metric(market):
    features, returns, rf = market
    result = run_backtest(MovingAverageCrossover(10), features, returns, rf)
    assert {
        "cagr", "ann_vol", "sharpe", "sortino", "max_drawdown", "calmar",
        "skew", "kurtosis", "time_in_market",
    } <= set(result.metrics)  # fmt: skip
    assert list(result.daily.columns) == ["position", "turnover", "cost", "return"]


def test_default_execution_config_reads_lab_yaml():
    assert ExecutionConfig.from_lab_config().cost_bps == 5
    assert ExecutionConfig.from_lab_config(cost_bps=1).cost_bps == 1


def test_daily_risk_free_compounds_to_the_annual_yield():
    daily = daily_risk_free(pd.Series([2.52]))
    assert (1 + daily.iloc[0]) ** 252 == pytest.approx(1.0252)


# --- leakage self-test -------------------------------------------------------------------------


def test_clean_signals_pass_the_leakage_test(market):
    features, *_ = market
    for signal in (ConstantSignal(0.5), MovingAverageCrossover(10)):
        assert len(check_leakage(signal, features)) == LEAKAGE_K


@pytest.mark.parametrize("leaky", [TomorrowPeek(), FullSampleZScore()], ids=lambda s: s.name)
def test_leaky_signals_fail_and_name_the_date(market, leaky):
    features, returns, rf = market
    with pytest.raises(LeakageError, match=r"\d{4}-\d{2}-\d{2}") as info:
        run_backtest(leaky, features, returns, rf)
    assert leaky.name in str(info.value)
    error_date = str(info.value).split("on ")[1][:10]
    assert error_date in features.index.strftime("%Y-%m-%d")


def test_leakage_dates_are_fixed_and_reproducible(market):
    features, *_ = market
    assert check_leakage(ConstantSignal(), features) == check_leakage(ConstantSignal(), features)
    assert check_leakage(ConstantSignal(), features, seed=1) != check_leakage(
        ConstantSignal(), features, seed=2
    )


def test_leakage_test_cannot_be_disabled(market):
    features, returns, rf = market
    with pytest.raises(BacktestError, match="cannot be disabled"):
        run_backtest(ConstantSignal(), features, returns, rf, leakage_k=0)


def test_run_reports_how_many_dates_were_checked(market):
    features, returns, rf = market
    assert run_backtest(ConstantSignal(), features, returns, rf).leakage_dates_checked == 25


# --- signal contract ---------------------------------------------------------------------------


def test_signal_protocol_is_satisfied_by_fixtures():
    assert isinstance(MovingAverageCrossover(5), Signal)


def test_warmup_nan_is_flat_but_interior_nan_is_an_error(market):
    features, *_ = market
    warm = pd.Series(1.0, index=features.index)
    warm.iloc[:5] = np.nan
    assert (compute_positions(ScriptedSignal(warm), features).iloc[:5] == 0).all()
    warm.iloc[50] = np.nan
    with pytest.raises(SignalError, match="NaN position"):
        compute_positions(ScriptedSignal(warm), features)


@pytest.mark.parametrize("bad", [1.5, -1.01, np.inf])
def test_out_of_range_positions_are_rejected(market, bad):
    features, *_ = market
    positions = pd.Series(0.0, index=features.index)
    positions.iloc[3] = bad
    with pytest.raises(SignalError, match="outside"):
        compute_positions(ScriptedSignal(positions), features)


def test_negative_positions_are_supported_by_the_contract(market):
    features, returns, rf = market
    result = run_backtest(ConstantSignal(-1.0), features, returns, rf, ExecutionConfig(cost_bps=0))
    assert result.daily["position"].eq(-1.0).all()
    assert result.returns.iloc[0] == pytest.approx(-returns.iloc[0] + 2 * RF)


def test_index_mismatch_is_an_error(market):
    features, returns, rf = market

    class WrongIndex(ConstantSignal):
        def compute(self, features):
            return pd.Series(1.0, index=features.index + pd.Timedelta(days=1))

    with pytest.raises(SignalError, match="indexed like"):
        compute_positions(WrongIndex(), features)
    with pytest.raises(BacktestError, match="return date"):
        run_backtest(ConstantSignal(), features.iloc[10:], returns, rf)


def test_missing_rates_and_returns_are_errors_not_fills(market):
    features, returns, rf = market
    holey = rf.copy()
    holey.iloc[10] = np.nan
    with pytest.raises(BacktestError, match="risk-free"):
        run_backtest(ConstantSignal(), features, returns, holey)
    gappy = returns.copy()
    gappy.iloc[3] = np.nan
    with pytest.raises(BacktestError, match="NaN"):
        run_backtest(ConstantSignal(), features, gappy, rf)


# --- optional execution settings ---------------------------------------------------------------


def test_defaults_leave_targets_untouched():
    targets = pd.Series([0.0, 1.0, -1.0, 0.3])
    pd.testing.assert_series_equal(apply_position_limits(targets, ExecutionConfig()), targets)


def test_sizing_bounds_clip_targets():
    targets = pd.Series([0.0, 1.0, -1.0, 0.3])
    limited = apply_position_limits(targets, ExecutionConfig(min_position=0.0, max_position=0.5))
    assert limited.tolist() == [0.0, 0.5, 0.0, 0.3]


def test_max_turnover_caps_daily_position_change():
    targets = pd.Series([1.0, 1.0, 1.0, 0.0, 0.0])
    limited = apply_position_limits(targets, ExecutionConfig(max_turnover=0.4))
    assert limited.tolist() == pytest.approx([0.4, 0.8, 1.0, 0.6, 0.2])
    assert limited.diff().abs().dropna().max() <= 0.4 + 1e-12


def test_bounds_flow_through_a_backtest(market):
    features, returns, rf = market
    cfg = ExecutionConfig(cost_bps=0, max_position=0.5)
    result = run_backtest(ConstantSignal(1.0), features, returns, rf, cfg)
    assert result.daily["position"].max() == 0.5


@pytest.mark.parametrize(
    "kwargs",
    [{"cost_bps": -1}, {"min_position": 0.5, "max_position": 0.2}, {"max_turnover": 0}],
)
def test_invalid_execution_config_is_rejected(kwargs):
    with pytest.raises(ValueError):
        ExecutionConfig(**kwargs)
