"""H-0002: hold the fund while smoothed implied volatility is below a level."""

from __future__ import annotations

import pandas as pd


class VixCalm:
    def __init__(self, window: int = 5, vix_max: float = 22):
        self.name = f"vix_calm_{window}_{vix_max:g}"
        self.params = {"window": window, "vix_max": vix_max}

    def compute(self, features: pd.DataFrame) -> pd.Series:
        smooth = features["vix"].astype("float64").rolling(max(1, int(round(self.params["window"])))).mean()
        return (smooth < self.params["vix_max"]).astype("float64").where(smooth.notna())


def make_signal(**params):
    return VixCalm(**params)
