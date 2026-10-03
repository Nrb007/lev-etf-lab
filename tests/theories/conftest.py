"""CEF fixtures: recorded ADX price (both bases) and NAV, never the network."""

from __future__ import annotations

import pandas as pd
import pytest

from core.config import LabConfig
from tests.conftest import FIXTURES, MINI_CONFIG
from theories.cef.data import fetch_fund_series, pull_cef

MINI_CEF_CONFIG = LabConfig.model_validate(
    {
        **MINI_CONFIG.model_dump(mode="json"),
        "universe": {
            **MINI_CONFIG.model_dump(mode="json")["universe"],
            "closed_end_funds": ["ADX"],
        },
    }
)


def fixture_cef_price(symbol: str) -> pd.DataFrame:
    return pd.read_csv(FIXTURES / f"CEF_{symbol}.csv", index_col=0, parse_dates=True)


def fixture_cef_nav(symbol: str) -> pd.Series:
    return pd.read_csv(FIXTURES / f"CEF_{symbol}.csv", index_col=0, parse_dates=True)["value"]


def fixture_fund(ticker: str = "ADX"):
    return fetch_fund_series(ticker, fetch_price=fixture_cef_price, fetch_nav=fixture_cef_nav)


@pytest.fixture
def cef_pulled(pulled):
    """The mini universe plus ADX, in one temporary cache."""
    result = pull_cef(
        ["ADX"],
        config=MINI_CEF_CONFIG,
        fetch_price=fixture_cef_price,
        fetch_nav=fixture_cef_nav,
        cache_dir=pulled["cache_dir"],
    )
    return {**pulled, "cef": result}
