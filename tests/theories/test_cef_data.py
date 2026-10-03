import pandas as pd
import pytest
from cryptography.fernet import Fernet

from core.config import load_lab_config
from core.data import cache
from core.data.loaders import FetchError, pull, universe_series
from core.data.splits import decrypt_holdout, load_prices, split_dates
from tests.conftest import fixture_price, fixture_rate
from tests.theories.conftest import (
    MINI_CEF_CONFIG,
    fixture_cef_nav,
    fixture_cef_price,
    fixture_fund,
)
from theories.cef.data import (
    align_price_and_nav,
    compare_with_cefconnect,
    load_cef,
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
    frame = load_prices(names, "train", cache_dir=directory, config=MINI_CEF_CONFIG)
    assert not frame.isna().any().any()
    assert (frame.index < split_dates(MINI_CEF_CONFIG).embargo_start).all()
    # the adjusted close is on a different basis from the quote; the quote and NAV are not
    assert (frame["ADX"] < frame[px_name("ADX")]).all()
    premium = frame[px_name("ADX")] / frame[nav_name("ADX")] - 1
    assert premium.between(-0.4, 0.1).all()
    meta = cache.read_meta(directory, nav_name("ADX"))
    assert "XADEX" in meta["source"] and meta["train_end_exclusive"] == str(
        split_dates(MINI_CEF_CONFIG).embargo_start.date()
    )
    assert cef_pulled["cef"]["series"] == {"ADX": "fetched"}


def test_pull_keeps_the_cache_unless_refreshed(cef_pulled):
    again = pull_cef(
        ["ADX"],
        config=MINI_CEF_CONFIG,
        fetch_price=lambda s: pytest.fail("fetched a cached fund"),
        fetch_nav=lambda s: pytest.fail("fetched a cached fund"),
        cache_dir=cef_pulled["cache_dir"],
    )
    assert again["series"] == {"ADX": "cached"}


def test_an_unregistered_fund_is_an_error_not_a_guess(tmp_path):
    with pytest.raises(FetchError, match="not a registered closed-end fund"):
        pull_cef(["ZZZ"], config=MINI_CEF_CONFIG, cache_dir=tmp_path)


def test_a_registered_fund_missing_from_the_config_is_refused(tmp_path, mini_config):
    with pytest.raises(FetchError, match="not under universe.closed_end_funds"):
        pull_cef(["ADX"], config=mini_config, cache_dir=tmp_path)


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
    assert series.index.max() < split_dates(MINI_CEF_CONFIG).embargo_start


def test_comparison_with_the_independent_source_counts_agreement():
    nav = fixture_cef_nav("XADEX")
    idx = nav.index[-50:]
    other = pd.DataFrame({"price": 1.0, "nav": nav.loc[idx]})
    other.iloc[3, 1] += 0.23  # one disagreement
    out = compare_with_cefconnect("ADX", fetch_nav=lambda s: nav, other=other)
    assert out["sessions_compared"] == 50
    assert out["nav_exact_share"] == pytest.approx(49 / 50)
    assert out["nav_max_abs_diff"] == pytest.approx(0.23, abs=1e-4)


def test_the_real_config_lists_the_fund_so_it_joins_the_holdout_path():

    names = universe_series(load_lab_config())
    assert {"ADX", "PX:ADX", "NAV:ADX"} <= set(names)


def _full_pull(tmp_path, key=None, **kwargs):
    return pull(
        MINI_CEF_CONFIG,
        fetch_price=fixture_price,
        fetch_rate=fixture_rate,
        fetch_fund=fixture_fund,
        cache_dir=tmp_path / "cache",
        holdout_path=tmp_path / "holdout.enc",
        holdout_key=key,
        **kwargs,
    )


def test_a_full_pull_splits_the_fund_at_holdout_start_into_the_encrypted_file(tmp_path):
    key = Fernet.generate_key()
    result = _full_pull(tmp_path, key)
    assert result["holdout_written"] is True
    frame = decrypt_holdout(tmp_path / "holdout.enc", key)
    assert {"ADX", "PX:ADX", "NAV:ADX", "QQQ"} <= set(frame.columns)
    assert frame.index.min() >= split_dates(MINI_CEF_CONFIG).holdout_start
    train = cache.read_series(tmp_path / "cache", "NAV:ADX")
    assert train.index.max() < split_dates(MINI_CEF_CONFIG).embargo_start
    assert frame["NAV:ADX"].notna().any()


def test_the_fund_hold_out_slice_is_not_written_without_a_key(tmp_path):
    assert _full_pull(tmp_path)["holdout_written"] is False
    assert not (tmp_path / "holdout.enc").exists()


def test_a_fund_pull_never_writes_the_holdout_file(tmp_path):
    pull_cef(
        ["ADX"],
        config=MINI_CEF_CONFIG,
        fetch_price=fixture_cef_price,
        fetch_nav=fixture_cef_nav,
        cache_dir=tmp_path / "cache",
    )
    assert not (tmp_path / "holdout.enc").exists()


def test_a_partly_cached_fund_is_refetched_as_a_group(tmp_path):
    _full_pull(tmp_path)
    (tmp_path / "cache" / "NAV_ADX.parquet").unlink()
    (tmp_path / "cache" / "NAV_ADX.meta.json").unlink()
    result = _full_pull(tmp_path)
    assert {result["series"][n] for n in ("ADX", "PX:ADX", "NAV:ADX")} == {"fetched"}


def test_a_configured_fund_without_a_fetcher_is_an_error(tmp_path):
    with pytest.raises(FetchError, match="no closed-end fund fetcher"):
        pull(
            MINI_CEF_CONFIG,
            fetch_price=fixture_price,
            fetch_rate=fixture_rate,
            cache_dir=tmp_path / "cache",
            holdout_path=tmp_path / "holdout.enc",
        )


def test_load_cef_returns_price_nav_and_premium_on_the_train_split(cef_pulled):
    frame = load_cef("ADX", cache_dir=cef_pulled["cache_dir"], config=MINI_CEF_CONFIG)
    assert list(frame.columns) == ["adj_close", "close", "nav", "premium"]
    assert (frame["premium"] == frame["close"] / frame["nav"] - 1).all()
    assert frame.index.max() < split_dates(MINI_CEF_CONFIG).embargo_start


def test_load_cef_cannot_return_a_row_on_or_after_the_embargo_start(tmp_path):
    dates = split_dates(MINI_CEF_CONFIG)
    price, nav = fixture_cef_price("ADX"), fixture_cef_nav("XADEX")
    assert price.index.max() >= dates.holdout_start  # the fixture reaches past the split
    for name, series in (("ADX", price["adj_close"]), ("PX:ADX", price["close"]), ("NAV:ADX", nav)):
        cache.write_series(tmp_path, name, series, {"source": "test"})  # the whole history
    frame = load_cef("ADX", cache_dir=tmp_path, config=MINI_CEF_CONFIG)
    assert len(frame) and frame.index.max() < dates.embargo_start
    assert (frame.index < dates.embargo_start).all()


def test_load_cef_serves_only_the_train_split(cef_pulled):
    with pytest.raises(ValueError, match="only serves split='train'"):
        load_cef("ADX", "holdout", cache_dir=cef_pulled["cache_dir"])  # type: ignore[arg-type]
