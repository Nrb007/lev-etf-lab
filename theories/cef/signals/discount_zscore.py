"""Discount-reversion signal for a closed-end fund.

Hold the fund while its discount to NAV is unusually wide against its own trailing history, and
hold cash otherwise. This module is self-contained on purpose: the pre-registration hash covers
this file alone, so nothing it depends on can change underneath a registered hypothesis.

Features used: ``raw_close`` (unadjusted price) and ``nav`` (unadjusted NAV). Premium is
``raw_close / nav - 1``. The signal for day t uses the premium measured at the close of day t and
its trailing window ending on t; the engine's t-to-t+1 lag is the only lag, so the position earned
on day t+1 is decided from information through the close of t (SPEC Section 5). A fund's NAV for
day t is in practice published after the close, so using it at the close of t is a small timing
idealization (docs/decisions.md).
"""

from __future__ import annotations

import pandas as pd

# A premium history flatter than one basis point has no range to be "wide" against; dividing by its
# rounding-noise standard deviation would fire the signal on nothing.
MIN_STD = 1e-4


class DiscountZScore:
    def __init__(self, window: int, entry_z: float):
        self.name = f"cef_discount_zscore_{window}_{entry_z:g}"
        self.params = {"window": window, "entry_z": entry_z}

    def compute(self, features: pd.DataFrame) -> pd.Series:
        window, entry_z = self.params["window"], self.params["entry_z"]
        premium = features["raw_close"] / features["nav"] - 1
        mean = premium.rolling(window).mean()
        std = premium.rolling(window).std()
        z = (premium - mean) / std
        warm = premium.rolling(window).count() == window
        return ((z <= -entry_z) & (std > MIN_STD)).astype("float64").where(warm)


def make_signal(window: int, entry_z: float) -> DiscountZScore:
    return DiscountZScore(window, entry_z)
