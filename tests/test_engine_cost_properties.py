"""Property tests on the cost model (SPEC Section 12, M2)."""

import numpy as np
import pandas as pd
from hypothesis import given
from hypothesis import strategies as st

from core.engine.backtest import simulate, trading_costs, turnover

position = st.floats(-1.0, 1.0, allow_nan=False)
positions = st.lists(position, min_size=1, max_size=60).map(
    lambda xs: pd.Series(xs, index=pd.bdate_range("2020-01-01", periods=len(xs)))
)
bps = st.floats(0, 500, allow_nan=False)
daily_return = st.floats(-0.5, 0.5, allow_nan=False)


@st.composite
def market(draw):
    pos = draw(positions)
    returns = pd.Series(
        draw(st.lists(daily_return, min_size=len(pos), max_size=len(pos))), index=pos.index
    )
    rf = pd.Series(
        draw(st.lists(st.floats(0, 0.001), min_size=len(pos), max_size=len(pos))), index=pos.index
    )
    return pos, returns, rf


@given(positions)
def test_turnover_is_the_absolute_position_change(pos):
    turn = turnover(pos)
    previous = pos.shift(1).fillna(0.0)  # a run starts from a flat book
    np.testing.assert_allclose(turn, (pos - previous).abs())
    assert (turn >= 0).all()


@given(positions, st.floats(0, 1))
def test_turnover_is_proportional_to_position_change(pos, scale):
    np.testing.assert_allclose(turnover(pos * scale), turnover(pos) * scale, atol=1e-12)


@given(positions, bps, st.floats(0, 1))
def test_cost_is_proportional_to_turnover(pos, cost_bps, scale):
    turn = turnover(pos)
    np.testing.assert_allclose(
        trading_costs(turn * scale, cost_bps), trading_costs(turn, cost_bps) * scale, atol=1e-15
    )


@given(st.floats(-1, 1), st.integers(2, 50), bps)
def test_zero_turnover_means_zero_cost(level, n, cost_bps):
    pos = pd.Series(level, index=pd.bdate_range("2020-01-01", periods=n))
    turn = turnover(pos)
    costs = trading_costs(turn, cost_bps)
    assert (turn.iloc[1:] == 0).all()
    assert (costs[turn == 0] == 0).all()
    assert costs.iloc[1:].sum() == 0


@given(positions, bps)
def test_costs_are_never_negative(pos, cost_bps):
    assert (trading_costs(turnover(pos), cost_bps) >= 0).all()


@given(market(), bps, bps)
def test_higher_cost_bps_never_improves_net_return(m, a, b):
    pos, returns, rf = m
    low, high = sorted([a, b])
    cheap = simulate(pos, returns, rf, low)
    dear = simulate(pos, returns, rf, high)
    # Identical positions and turnover; only the cost rate differs.
    pd.testing.assert_series_equal(cheap["position"], dear["position"])
    pd.testing.assert_series_equal(cheap["turnover"], dear["turnover"])
    assert (dear["return"] <= cheap["return"] + 1e-15).all()
    assert dear["return"].sum() <= cheap["return"].sum() + 1e-12
    assert (dear["cost"] >= cheap["cost"] - 1e-15).all()


@given(market())
def test_zero_cost_net_return_is_the_gross_return(m):
    pos, returns, rf = m
    out = simulate(pos, returns, rf, 0.0)
    np.testing.assert_allclose(out["return"], pos * returns + (1 - pos) * rf, atol=1e-15)
    assert (out["cost"] == 0).all()
