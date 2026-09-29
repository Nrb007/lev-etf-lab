import pandas as pd
import pytest
from cryptography.fernet import Fernet

from core.data import cache
from core.data.cache import CacheCorruptError
from core.data.loaders import (
    ADJUSTMENT,
    FetchError,
    align_to_calendar,
    pull,
    universe_series,
)
from core.data.nyse import nyse_sessions
from core.data.splits import decrypt_holdout, split_dates
from tests.conftest import fixture_price, fixture_rate


def test_universe_series_covers_config(mini_config):
    assert universe_series(mini_config) == [
        "QQQ",
        "TQQQ",
        "^VIX",
        "^VIX3M",
        "FRED:DFF",
        "FRED:DGS3MO",
    ]


def test_pull_caches_train_slice_with_sidecar(pulled, mini_config):
    cache_dir = pulled["cache_dir"]
    status = pulled["result"]["series"]
    assert status["QQQ"] == status["FRED:DGS3MO"] == "fetched"
    assert status["^VIX3M"] == "unavailable_optional"
    assert not cache.has_series(cache_dir, "^VIX3M")

    embargo_start = split_dates(mini_config).embargo_start
    for name in ["QQQ", "TQQQ", "^VIX", "FRED:DFF", "FRED:DGS3MO"]:
        series = cache.read_series(cache_dir, name)
        meta = cache.read_meta(cache_dir, name)
        assert series.index.max() < embargo_start
        assert meta["row_count"] == len(series)
        assert meta["content_hash"] == cache.content_hash(series.rename("value"))
        assert meta["fetch_time"]
        assert meta["source"] in {"yfinance", "FRED"}
    assert cache.read_meta(cache_dir, "TQQQ")["adjustment"] == ADJUSTMENT
    assert ADJUSTMENT["auto_adjust"] is True


def test_cache_hit_does_not_refetch_until_refresh(pulled, mini_config):
    calls = []

    def counting_price(ticker):
        calls.append(ticker)
        return fixture_price(ticker)

    kwargs = dict(
        fetch_rate=fixture_rate,
        cache_dir=pulled["cache_dir"],
        holdout_path=pulled["tmp_path"] / "holdout.enc",
    )
    again = pull(mini_config, fetch_price=counting_price, **kwargs)
    assert calls == ["^VIX3M"]  # only the never-cached optional series is retried
    assert again["series"]["QQQ"] == "cached"

    pull(mini_config, fetch_price=counting_price, refresh=True, **kwargs)
    assert set(calls) == {"QQQ", "TQQQ", "^VIX", "^VIX3M"}


def test_required_series_failure_is_loud(tmp_path, mini_config):
    def failing(ticker):
        if ticker == "QQQ":
            raise ConnectionError("boom")
        return fixture_price(ticker)

    with pytest.raises(FetchError, match="QQQ: boom"):
        pull(
            mini_config,
            fetch_price=failing,
            fetch_rate=fixture_rate,
            cache_dir=tmp_path / "c",
            holdout_path=tmp_path / "h.enc",
        )


def test_tampered_cache_is_detected(pulled):
    parquet = pulled["cache_dir"] / "QQQ.parquet"
    frame = pd.read_parquet(parquet)
    frame.iloc[3, 0] *= 2
    frame.to_parquet(parquet)
    with pytest.raises(CacheCorruptError):
        cache.read_series(pulled["cache_dir"], "QQQ")


def test_align_logs_missing_sessions_and_never_fills():
    sessions = nyse_sessions("2019-03-01", "2019-03-29")
    series = pd.Series(range(1, len(sessions) + 1), index=sessions, dtype="float64")
    hole = sessions[5]
    series = series.drop(hole)
    aligned, events = align_to_calendar(series, "X")
    assert pd.isna(aligned[hole])
    assert {"kind": "missing", "date": str(hole.date())} in events
    assert aligned.notna().sum() == len(series)


def test_align_forward_fill_is_logged():
    sessions = nyse_sessions("2019-03-01", "2019-03-29")
    series = pd.Series(1.0, index=sessions).drop(sessions[5])
    aligned, events = align_to_calendar(series, "FRED:X", fill="ffill")
    assert aligned[sessions[5]] == 1.0
    assert events == [{"kind": "forward_fill", "date": str(sessions[5].date())}]


def test_align_drops_and_logs_non_session_dates():
    sessions = nyse_sessions("2019-03-01", "2019-03-15")
    weekend = pd.Timestamp("2019-03-09")
    series = pd.Series(1.0, index=sessions.append(pd.DatetimeIndex([weekend])).sort_values())
    aligned, events = align_to_calendar(series, "FRED:X")
    assert weekend not in aligned.index
    assert events[0]["kind"] == "dropped_non_session"
    assert events[0]["count"] == 1


def test_pull_alignment_log_is_recorded_for_holiday_gap_rates(pulled):
    meta = cache.read_meta(pulled["cache_dir"], "FRED:DGS3MO")
    assert meta["fill_policy"] == "ffill"
    kinds = {e["kind"] for e in meta["alignment_log"]}
    assert "forward_fill" in kinds  # Treasury holidays that NYSE trades through
    assert not cache.read_series(pulled["cache_dir"], "FRED:DGS3MO").isna().any()


def test_holdout_roundtrip_uses_disposable_key(tmp_path, mini_config):
    key = Fernet.generate_key()
    holdout = tmp_path / "holdout.enc"
    result = pull(
        mini_config,
        fetch_price=fixture_price,
        fetch_rate=fixture_rate,
        cache_dir=tmp_path / "cache",
        holdout_path=holdout,
        holdout_key=key,
    )
    assert result["holdout_written"] is True
    assert b"PAR1" not in holdout.read_bytes()  # ciphertext, not parquet

    frame = decrypt_holdout(holdout, key)
    assert {"QQQ", "TQQQ", "^VIX", "FRED:DFF"} <= set(frame.columns)
    assert frame.index.min() >= split_dates(mini_config).holdout_start
    with pytest.raises(Exception):  # noqa: B017 - any wrong key must fail
        decrypt_holdout(holdout, Fernet.generate_key())


def test_no_key_means_no_holdout_file(pulled):
    assert pulled["result"]["holdout_written"] is False
    assert not (pulled["tmp_path"] / "holdout.enc").exists()
