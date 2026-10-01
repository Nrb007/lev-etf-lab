"""H-0004: hold the fund only while smoothed implied volatility is HIGH (buy the fear)."""

from __future__ import annotations

import pandas as pd


class FearBuyer:
    def __init__(self, window: int = 5, vix_min: float = 22):
        self.name = f"fear_buyer_{window}_{vix_min:g}"
        self.params = {"window": window, "vix_min": vix_min}

    def compute(self, features: pd.DataFrame) -> pd.Series:
        smooth = features["vix"].astype("float64").rolling(max(1, int(round(self.params["window"])))).mean()
        return (smooth > self.params["vix_min"]).astype("float64").where(smooth.notna())


def make_signal(**params):
    return FearBuyer(**params)
