"""Discount-reversion signal for a closed-end fund.

Hold the fund while its discount to NAV is unusually wide against its own trailing history, and
hold cash otherwise. This module is self-contained on purpose: the pre-registration hash covers
this file alone, so nothing it depends on can change underneath a registered hypothesis.

Features used: ``raw_close`` (unadjusted price) and ``nav`` (unadjusted NAV). Premium is
``raw_close / nav - 1``. A fund's NAV for day t is struck at the close and published after it, so
the premium used on day t is the one measured on day t-1: the position on t is decided from
information that was public at the close of t.
"""

from __future__ import annotations

import pandas as pd

# A premium history flatter than one basis point has no range to be "wide" against; dividing by its
# rounding-noise standard deviation would fire the signal on nothing.
MIN_STD = 1e-4


class PremiumReversion:
    def __init__(self, window: int, entry_z: float):
        self.name = f"cef_premium_reversion_{window}_{entry_z:g}"
        self.params = {"window": window, "entry_z": entry_z}

    def compute(self, features: pd.DataFrame) -> pd.Series:
        window, entry_z = self.params["window"], self.params["entry_z"]
        premium = (features["raw_close"] / features["nav"] - 1).shift(1)
        mean = premium.rolling(window).mean()
        std = premium.rolling(window).std()
        z = (premium - mean) / std
        warm = premium.rolling(window).count() == window
        return ((z <= -entry_z) & (std > MIN_STD)).astype("float64").where(warm)


def make_signal(window: int, entry_z: float) -> PremiumReversion:
    return PremiumReversion(window, entry_z)
