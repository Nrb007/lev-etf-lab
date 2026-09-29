import inspect
import tempfile
from pathlib import Path

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.config import LabConfig
from core.data import cache
from core.data.nyse import nyse_sessions
from core.data.splits import SplitDates, load_prices, split_dates, split_frame

REPO = Path(__file__).resolve().parents[1]


def _config(holdout_start: str, embargo: int) -> LabConfig:
    return LabConfig.model_validate(
        {
            "universe": {
                "underlyings": ["QQQ"],
                "leveraged_3x": [],
                "loaded_not_used": [],
                "volatility": [],
                "rates": [],
            },
            "holdout_start": holdout_start,
            "embargo_trading_days": embargo,
            "cost_bps": 5,
        }
    )


def test_embargo_is_21_sessions_before_holdout_start(mini_config):
    dates = split_dates(mini_config)
    window = nyse_sessions("2019-06-01", "2019-12-31")
    embargoed = window[(window >= dates.embargo_start) & (window < dates.holdout_start)]
    assert len(embargoed) == mini_config.embargo_trading_days == 21
    assert dates.holdout_start == pd.Timestamp("2019-10-01")


def test_default_config_split_dates():
    dates = split_dates()
    assert dates.holdout_start == pd.Timestamp("2024-07-01")
    assert dates.embargo_start < dates.holdout_start


def test_split_frame_excludes_embargo_from_both_sides():
    dates = SplitDates(pd.Timestamp("2019-09-02"), pd.Timestamp("2019-10-01"))
    index = pd.date_range("2019-08-26", "2019-10-10", freq="B")
    train, holdout = split_frame(pd.Series(1.0, index=index), dates)
    assert train.index.max() < dates.embargo_start
    assert holdout.index.min() >= dates.holdout_start
    assert not set(train.index) & set(holdout.index)
    assert len(train) + len(holdout) < len(index)


def test_load_prices_train_stops_before_embargo(pulled, mini_config):
    frame = load_prices(
        ["QQQ", "TQQQ", "FRED:DFF"], "train", cache_dir=pulled["cache_dir"], config=mini_config
    )
    assert frame.index.max() < split_dates(mini_config).embargo_start
    assert list(frame.columns) == ["QQQ", "TQQQ", "FRED:DFF"]


def test_load_prices_refuses_any_other_split(pulled, mini_config):
    for split in ["holdout", "all", "", None]:
        with pytest.raises(ValueError):
            load_prices("QQQ", split, cache_dir=pulled["cache_dir"], config=mini_config)  # type: ignore[arg-type]


def test_load_prices_truncates_even_a_poisoned_cache(tmp_path, mini_config):
    """Hard truncation: rows past the embargo/holdout planted in the cache are never returned."""
    index = nyse_sessions("2019-06-03", "2019-12-31")
    cache.write_series(tmp_path, "QQQ", pd.Series(100.0, index=index), {"source": "test"})
    dates = split_dates(mini_config)
    assert index.max() >= dates.holdout_start  # the cache really does contain post-holdout rows

    frame = load_prices("QQQ", "train", cache_dir=tmp_path, config=mini_config)
    assert len(frame) < len(index)
    assert (frame.index < dates.embargo_start).all()
    assert not (frame.index >= dates.holdout_start).any()


@settings(max_examples=25, deadline=None)
@given(
    holdout=st.dates(
        min_value=pd.Timestamp("2016-01-01").date(), max_value=pd.Timestamp("2024-12-31").date()
    ),
    embargo=st.integers(min_value=0, max_value=40),
)
def test_load_prices_never_returns_rows_at_or_after_holdout_start(holdout, embargo):
    config = _config(holdout.isoformat(), embargo)
    index = nyse_sessions("2015-06-01", "2025-06-30")
    with tempfile.TemporaryDirectory() as tmp:
        cache.write_series(Path(tmp), "QQQ", pd.Series(1.0, index=index), {"source": "test"})
        frame = load_prices("QQQ", "train", cache_dir=Path(tmp), config=config)
    assert (frame.index < pd.Timestamp(holdout)).all()
    assert len(frame) == 0 or frame.index.max() <= pd.Timestamp(holdout) - pd.Timedelta(
        days=embargo
    )


def test_load_prices_signature_offers_no_way_to_ask_for_holdout():
    params = inspect.signature(load_prices).parameters
    assert params["split"].default == "train"
    assert set(params) == {"tickers", "split", "cache_dir", "config"}


def test_only_the_judge_may_call_decrypt_holdout():
    offenders = []
    for path in (REPO / "core").rglob("*.py"):
        rel = path.relative_to(REPO).as_posix()
        if rel in {"core/data/splits.py", "core/judge/holdout.py"}:
            continue
        if "decrypt_holdout" in path.read_text():
            offenders.append(rel)
    assert offenders == []
