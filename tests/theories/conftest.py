"""CEF fixtures: recorded ADX price (both bases) and NAV, never the network."""

from __future__ import annotations

import pandas as pd
import pytest

from tests.conftest import FIXTURES, MINI_CONFIG
from theories.cef.data import pull_cef


def fixture_cef_price(symbol: str) -> pd.DataFrame:
    return pd.read_csv(FIXTURES / f"CEF_{symbol}.csv", index_col=0, parse_dates=True)


def fixture_cef_nav(symbol: str) -> pd.Series:
    return pd.read_csv(FIXTURES / f"CEF_{symbol}.csv", index_col=0, parse_dates=True)["value"]


@pytest.fixture
def cef_pulled(pulled):
    """The mini universe plus ADX, in one temporary cache."""
    result = pull_cef(
        ["ADX"],
        config=MINI_CONFIG,
        fetch_price=fixture_cef_price,
        fetch_nav=fixture_cef_nav,
        cache_dir=pulled["cache_dir"],
    )
    return {**pulled, "cef": result}
