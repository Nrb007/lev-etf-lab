"""Shared fixtures: a mini universe served from recorded CSVs, never the network."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from core.config import LabConfig
from core.data import cache
from core.data.loaders import pull

FIXTURES = Path(__file__).parent / "fixtures"

MINI_CONFIG = LabConfig.model_validate(
    {
        "universe": {
            "underlyings": ["QQQ"],
            "leveraged_3x": ["TQQQ"],
            "loaded_not_used": [],
            "volatility": ["^VIX", "^VIX3M"],  # ^VIX3M has no fixture: exercises "optional"
            "rates": [
                {"source": "FRED", "series": "DFF"},
                {"source": "FRED", "series": "DGS3MO"},
            ],
        },
        "holdout_start": "2019-10-01",
        "embargo_trading_days": 21,
        "cost_bps": 5,
    }
)


def _read(stem: str) -> pd.Series:
    path = FIXTURES / f"{stem}.csv"
    if not path.exists():
        raise FileNotFoundError(f"no recorded fixture for {stem}")
    frame = pd.read_csv(path, index_col=0, parse_dates=True)
    return frame["value"]


def fixture_price(ticker: str) -> pd.Series:
    return _read(ticker.replace("^", "IDX_")).rename(ticker)


def fixture_rate(series: str) -> pd.Series:
    return _read(f"FRED_{series}").rename(cache.fred_name(series))


@pytest.fixture
def mini_config() -> LabConfig:
    return MINI_CONFIG


@pytest.fixture
def pulled(tmp_path, mini_config):
    """Result of a full pull against the fixtures into a temporary data dir."""
    cache_dir = tmp_path / "cache"
    result = pull(
        mini_config,
        fetch_price=fixture_price,
        fetch_rate=fixture_rate,
        cache_dir=cache_dir,
        holdout_path=tmp_path / "holdout.enc",
    )
    return {"cache_dir": cache_dir, "result": result, "tmp_path": tmp_path}
