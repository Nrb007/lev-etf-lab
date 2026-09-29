import numpy as np
import pandas as pd
import pytest

from core.engine.metrics import TRADING_DAYS, cagr, compute_metrics, max_drawdown


def series(values):
    return pd.Series(values, index=pd.bdate_range("2020-01-01", periods=len(values)), dtype=float)


def test_constant_return_metrics():
    r = series([0.001] * TRADING_DAYS)
    m = compute_metrics(r, in_market=pd.Series(True, index=r.index))
    assert m["cagr"] == pytest.approx(1.001**TRADING_DAYS - 1)
    assert m["ann_vol"] == pytest.approx(0.0, abs=1e-12)
    assert np.isnan(m["sharpe"])  # zero volatility: undefined, not infinite
    assert m["max_drawdown"] == 0.0
    assert np.isnan(m["calmar"])
    assert m["time_in_market"] == 1.0


def test_drawdown_and_calmar():
    r = series([0.10, -0.50, 0.20, 0.0])
    assert max_drawdown(r) == pytest.approx(-0.5)
    m = compute_metrics(r)
    assert m["calmar"] == pytest.approx(cagr(r) / 0.5)


def test_sharpe_sortino_match_definitions():
    rng = np.random.default_rng(1)
    r = series(rng.normal(0.0005, 0.01, 500))
    rf = series([0.0001] * 500)
    m = compute_metrics(r, rf)
    excess = r - rf
    assert m["sharpe"] == pytest.approx(excess.mean() * 252 / (r.std() * np.sqrt(252)))
    down = np.sqrt((np.minimum(excess, 0) ** 2).mean() * 252)
    assert m["sortino"] == pytest.approx(excess.mean() * 252 / down)
    assert m["skew"] == pytest.approx(r.skew())
    assert m["kurtosis"] == pytest.approx(r.kurt())


def test_time_in_market_is_share_of_days_invested():
    r = series([0.01, 0.02, -0.01, 0.0])
    m = compute_metrics(r, in_market=pd.Series([True, False, True, False], index=r.index))
    assert m["time_in_market"] == 0.5


def test_rejects_empty_and_nan():
    with pytest.raises(ValueError):
        compute_metrics(series([]))
    with pytest.raises(ValueError):
        compute_metrics(series([0.01, np.nan]))
