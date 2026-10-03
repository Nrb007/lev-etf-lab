import numpy as np
import pandas as pd

from core.engine.backtest import check_leakage
from core.engine.signal_api import compute_positions
from theories.cef.signals.premium_reversion import make_signal


def _features(n=400, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-02", periods=n)
    nav = pd.Series(20 * np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=idx)
    premium = pd.Series(-0.12 + 0.03 * rng.standard_normal(n), index=idx)
    return pd.DataFrame({"close": nav, "raw_close": nav * (1 + premium), "nav": nav})


def test_long_after_an_unusually_wide_discount_and_cash_otherwise():
    f = _features()
    f.iloc[300, f.columns.get_loc("raw_close")] = f["nav"].iloc[300] * 0.6  # -40% discount
    pos = compute_positions(make_signal(63, 1.0), f)
    assert pos.iloc[301] == 1.0  # the wide discount is public at the close of 300, acted on at 301
    assert pos.iloc[:63].eq(0).all()  # warm-up
    assert 0 < pos.mean() < 0.5


def test_the_premium_used_on_day_t_is_the_one_measured_on_day_t_minus_1():
    f = _features()
    base = compute_positions(make_signal(63, 1.0), f)
    f2 = f.copy()
    f2.iloc[350, f2.columns.get_loc("raw_close")] *= 0.5  # day 350's quote changes ...
    changed = compute_positions(make_signal(63, 1.0), f2)
    assert changed.iloc[350] == base.iloc[350]  # ... but day 350's own position does not
    assert changed.iloc[351] != base.iloc[351]


def test_engine_leakage_check_passes_for_every_grid_point():
    f = _features()
    for window in (63, 126, 252):
        for entry in (0.5, 1.0, 1.5):
            assert check_leakage(make_signal(window, entry), f)


def test_a_constant_premium_gives_a_flat_position_not_a_nan_error():
    f = _features()
    f["raw_close"] = f["nav"] * 0.9
    assert compute_positions(make_signal(63, 1.0), f).eq(0).all()
