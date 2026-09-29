import json

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.data.nyse import nyse_sessions
from core.data.synthetic import (
    CORRELATION_TARGET,
    DEFAULT_EXPENSE_RATIO,
    DEFAULT_FINANCING_SPREAD,
    daily_returns,
    research_prices,
    synthetic_prices,
    synthetic_returns,
    underlying_for,
    validate_against_real,
)

INDEX = pd.date_range("2020-01-01", periods=5, freq="B")
returns_strategy = st.lists(
    st.floats(min_value=-0.2, max_value=0.2, allow_nan=False), min_size=2, max_size=40
)
rate_strategy = st.floats(min_value=0.0, max_value=10.0, allow_nan=False)
small = st.floats(min_value=0.0, max_value=0.03, allow_nan=False)


def _series(values):
    return pd.Series(values, index=pd.date_range("2020-01-01", periods=len(values), freq="B"))


def test_formula_matches_section_4_2_by_hand():
    r_u = _series([0.01, -0.02])
    dff = _series([5.0, 5.0])  # percent
    out = synthetic_returns(r_u, dff, 3, financing_spread=0.005, expense_ratio=0.0084)
    financing = (0.05 + 0.005) / 252
    expected = 3 * 0.01 - 2 * financing - 0.0084 / 252
    assert out.iloc[0] == pytest.approx(expected)
    assert out.iloc[1] == pytest.approx(3 * -0.02 - 2 * financing - 0.0084 / 252)


def test_negative_leverage_uses_the_same_formula():
    r_u = _series([0.01])
    out = synthetic_returns(r_u, _series([4.0]), -3, financing_spread=0.0, expense_ratio=0.0)
    assert out.iloc[0] == pytest.approx(-3 * 0.01 + 4 * (0.04 / 252))


@given(returns_strategy, rate_strategy, small, small)
def test_one_x_fund_is_underlying_minus_fee(rs, dff, spread, fee):
    r_u = _series(rs)
    out = synthetic_returns(
        r_u, _series([dff] * len(rs)), 1, financing_spread=spread, expense_ratio=fee
    )
    np.testing.assert_allclose(out, r_u - fee / 252, atol=1e-12)


@given(returns_strategy, rate_strategy, small, small, st.floats(-4, 4), st.floats(-4, 4))
def test_difference_between_leverages_is_linear(rs, dff, spread, fee, l1, l2):
    r_u, rate = _series(rs), _series([dff] * len(rs))
    kw = dict(financing_spread=spread, expense_ratio=fee)
    diff = synthetic_returns(r_u, rate, l1, **kw) - synthetic_returns(r_u, rate, l2, **kw)
    financing = (rate / 100 + spread) / 252
    np.testing.assert_allclose(diff, (l1 - l2) * (r_u - financing), atol=1e-9)


@given(rate_strategy, small, small)
def test_flat_market_at_zero_financing_only_pays_the_fee(dff, spread, fee):
    n = 6
    out = synthetic_returns(
        _series([0.0] * n), _series([dff] * n), 1, financing_spread=spread, expense_ratio=fee
    )
    np.testing.assert_allclose(out, -fee / 252, atol=1e-12)


@given(returns_strategy, small, small)
def test_higher_expense_ratio_never_raises_returns(rs, fee_a, fee_b):
    lo, hi = sorted([fee_a, fee_b])
    r_u, rate = _series(rs), _series([3.0] * len(rs))
    a = synthetic_returns(r_u, rate, 3, expense_ratio=lo)
    b = synthetic_returns(r_u, rate, 3, expense_ratio=hi)
    assert (b <= a + 1e-15).all()


@settings(max_examples=50)
@given(st.lists(st.floats(min_value=-0.5, max_value=0.5, allow_nan=False), min_size=2, max_size=60))
def test_compounded_price_is_positive_and_matches_returns(rs):
    returns = _series(rs)
    prices = synthetic_prices(returns, start_price=100.0)
    assert (prices > 0).all()
    np.testing.assert_allclose(daily_returns(prices).iloc[1:], returns.iloc[1:], atol=1e-9)


def test_synthetic_prices_refuse_gaps_and_wipeouts():
    with pytest.raises(ValueError, match="data gap"):
        synthetic_prices(_series([0.01, float("nan"), 0.02]))
    with pytest.raises(ValueError, match="-100%"):
        synthetic_prices(_series([0.01, -1.0, 0.02]))


def test_returns_do_not_span_missing_days():
    prices = _series([100.0, float("nan"), 102.0, 103.0])
    r = daily_returns(prices)
    assert r.isna().tolist() == [True, True, True, False]


def test_default_parameters_are_documented_choices():
    assert DEFAULT_FINANCING_SPREAD == 0.005
    assert DEFAULT_EXPENSE_RATIO == 0.0095


def test_underlying_mapping_and_tecl_gap():
    assert underlying_for("TQQQ") == "QQQ"
    assert underlying_for("SOXL") == "SOXX"
    with pytest.raises(ValueError, match="TECL"):
        underlying_for("TECL")


def test_research_universe_records_which_was_used(pulled, mini_config):
    kw = dict(cache_dir=pulled["cache_dir"], config=mini_config)
    real, real_meta = research_prices("TQQQ", "real", **kw)
    synth, synth_meta = research_prices("TQQQ", "synthetic_long", leverage=3, **kw)
    assert real_meta["research_universe"] == "real"
    assert synth_meta["research_universe"] == "synthetic_long"
    assert synth_meta["underlying"] == "QQQ"
    assert synth.iloc[0] == pytest.approx(100 * (1 + synthetic_first_return(pulled, mini_config)))
    with pytest.raises(ValueError):
        research_prices("TQQQ", "bogus", **kw)  # type: ignore[arg-type]


def synthetic_first_return(pulled, mini_config):
    from core.data.splits import load_prices

    frame = load_prices(
        ["QQQ", "FRED:DFF"], "train", cache_dir=pulled["cache_dir"], config=mini_config
    )
    r_u = daily_returns(frame["QQQ"]).iloc[1]
    financing = (frame["FRED:DFF"].iloc[1] / 100 + DEFAULT_FINANCING_SPREAD) / 252
    return 3 * r_u - 2 * financing - DEFAULT_EXPENSE_RATIO / 252


def test_validate_against_real_on_fixtures(pulled, mini_config, tmp_path):
    kw = dict(cache_dir=pulled["cache_dir"], config=mini_config)
    real, _ = research_prices("TQQQ", "real", **kw)
    synth, meta = research_prices("TQQQ", "synthetic_long", leverage=3, **kw)
    out = tmp_path / "data_validation.json"
    result = validate_against_real(
        daily_returns(synth), real.rename("TQQQ"), meta=meta, out_path=out
    )

    assert 0.99 < result["daily_return_correlation"] <= 1.0
    assert result["correlation_target"] == CORRELATION_TARGET
    assert result["correlation_target_met"] == (result["daily_return_correlation"] > 0.999)
    assert result["research_universe"] == "synthetic_long"
    assert result["overlap"]["days"] > 100
    assert result["tracking_error_annualized"] > 0
    assert set(result["residual_autocorrelation"]) == {f"lag{k}" for k in range(1, 6)}
    assert set(result["diagnostics"]["correlation_by_horizon_days"]) == {"1", "2", "5", "21"}
    assert json.loads(out.read_text())["TQQQ_3x"]["fund"] == "TQQQ"


def test_validate_against_real_perfect_replica(tmp_path):
    sessions = nyse_sessions("2019-01-02", "2019-06-28")
    rng = np.random.default_rng(0)
    real = pd.Series(
        100 * np.cumprod(1 + rng.normal(0, 0.02, len(sessions))), index=sessions, name="X"
    )
    result = validate_against_real(daily_returns(real), real, out_path=tmp_path / "v.json")
    assert result["daily_return_correlation"] == pytest.approx(1.0)
    assert result["tracking_error_annualized"] == pytest.approx(0.0, abs=1e-12)
    assert result["cumulative_return"]["gap_real_minus_synthetic"] == pytest.approx(0.0, abs=1e-9)
    assert result["correlation_target_met"] is True


def test_validate_against_real_merges_results_per_fund(tmp_path):
    sessions = nyse_sessions("2019-01-02", "2019-06-28")
    rng = np.random.default_rng(1)
    out = tmp_path / "v.json"
    for fund in ["AAA", "BBB"]:
        real = pd.Series(
            100 * np.cumprod(1 + rng.normal(0, 0.02, len(sessions))), index=sessions, name=fund
        )
        validate_against_real(daily_returns(real), real, meta={"leverage": 3.0}, out_path=out)
    assert set(json.loads(out.read_text())) == {"AAA_3x", "BBB_3x"}
