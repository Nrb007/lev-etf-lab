import pandas as pd
import pytest

from core.config import load_lab_config
from core.data import cache
from core.data.loaders import FetchError
from core.data.splits import load_prices, split_dates
from tests.conftest import MINI_CONFIG
from tests.theories.conftest import fixture_cef_nav, fixture_cef_price
from theories.cef.data import (
    align_price_and_nav,
    compare_with_cefconnect,
    nav_name,
    pull_cef,
    px_name,
)


def _series(values, start="2019-01-02"):
    idx = pd.bdate_range(start, periods=len(values))
    return pd.Series(values, index=idx, dtype="float64")


def test_pull_caches_price_unadjusted_price_and_nav_on_one_index(cef_pulled):
    directory = cef_pulled["cache_dir"]
    names = ["ADX", px_name("ADX"), nav_name("ADX")]
    frame = load_prices(names, "train", cache_dir=directory, config=MINI_CONFIG)
    assert not frame.isna().any().any()
    assert (frame.index < split_dates(MINI_CONFIG).embargo_start).all()
    # the adjusted close is on a different basis from the quote; the quote and NAV are not
    assert (frame["ADX"] < frame[px_name("ADX")]).all()
    premium = frame[px_name("ADX")] / frame[nav_name("ADX")] - 1
    assert premium.between(-0.4, 0.1).all()
    assert cache.read_meta(directory, nav_name("ADX"))["theory"] == "cef"
    assert cef_pulled["cef"]["series"] == {"ADX": "fetched"}


def test_pull_keeps_the_cache_unless_refreshed(cef_pulled):
    again = pull_cef(
        ["ADX"],
        config=MINI_CONFIG,
        fetch_price=lambda s: pytest.fail("fetched a cached fund"),
        fetch_nav=lambda s: pytest.fail("fetched a cached fund"),
        cache_dir=cef_pulled["cache_dir"],
    )
    assert again["series"] == {"ADX": "cached"}


def test_an_unregistered_fund_is_an_error_not_a_guess(tmp_path):
    with pytest.raises(FetchError, match="not a registered closed-end fund"):
        pull_cef(["ZZZ"], config=MINI_CONFIG, cache_dir=tmp_path)


def test_a_missing_nav_session_is_dropped_everywhere_and_logged_never_filled():
    price = fixture_cef_price("ADX")
    nav = fixture_cef_nav("XADEX")
    gap = nav.index[100]
    aligned, events = align_price_and_nav(price["close"], price["adj_close"], nav.drop(gap), "ADX")
    assert gap not in aligned["close"].index and gap not in aligned["nav"].index
    assert gap not in aligned["adj_close"].index
    assert {"kind": "missing", "source": "nav", "date": str(gap.date())} in events


def test_too_many_gaps_refuse_the_fetch():
    price = fixture_cef_price("ADX")
    nav = fixture_cef_nav("XADEX").iloc[::2]  # every other session
    with pytest.raises(FetchError, match="lack a price or a NAV"):
        align_price_and_nav(price["close"], price["adj_close"], nav, "ADX")


def test_an_incredible_premium_refuses_the_fetch():
    price = fixture_cef_price("ADX")
    nav = fixture_cef_nav("XADEX").copy()
    nav.iloc[50] *= 3
    with pytest.raises(FetchError, match="not credible"):
        align_price_and_nav(price["close"], price["adj_close"], nav, "ADX")


def test_the_hold_out_slice_is_never_cached(cef_pulled):
    series = cache.read_series(cef_pulled["cache_dir"], nav_name("ADX"))
    assert series.index.max() < split_dates(MINI_CONFIG).embargo_start


def test_comparison_with_the_independent_source_counts_agreement():
    nav = fixture_cef_nav("XADEX")
    idx = nav.index[-50:]
    other = pd.DataFrame({"price": 1.0, "nav": nav.loc[idx]})
    other.iloc[3, 1] += 0.23  # one disagreement
    out = compare_with_cefconnect("ADX", fetch_nav=lambda s: nav, other=other)
    assert out["sessions_compared"] == 50
    assert out["nav_exact_share"] == pytest.approx(49 / 50)
    assert out["nav_max_abs_diff"] == pytest.approx(0.23, abs=1e-4)


def test_real_config_has_no_cef_series_so_the_holdout_file_is_unchanged():
    from core.data.loaders import universe_series

    assert not [n for n in universe_series(load_lab_config()) if "ADX" in n]
