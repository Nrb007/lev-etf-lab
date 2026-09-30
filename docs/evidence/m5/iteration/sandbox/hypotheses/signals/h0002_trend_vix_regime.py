"""H-0002: hold only when the underlying trends up and implied vol is not spiking."""

from __future__ import annotations

import pandas as pd


class TrendVixRegime:
    def __init__(self, trend_window: int = 100, vix_ratio: float = 1.25):
        self.name = f"trend_vix_regime_{trend_window}_{vix_ratio:g}"
        self.params = {"trend_window": trend_window, "vix_ratio": vix_ratio}

    def compute(self, features: pd.DataFrame) -> pd.Series:
        base = features["underlying"] if "underlying" in features else features["close"]
        base = base.astype("float64")
        w = int(self.params["trend_window"])
        mean = base.rolling(w).mean()
        trend_ok = base > mean
        valid = mean.notna()
        ok = trend_ok
        if "vix" in features and features["vix"].notna().any():
            vix = features["vix"].astype("float64")
            vix_base = vix.rolling(w).mean()
            calm = vix <= self.params["vix_ratio"] * vix_base
            ok = trend_ok & calm
            valid = valid & vix_base.notna() & vix.notna()
        return ok.astype("float64").where(valid)


def make_signal(**params):
    return TrendVixRegime(**params)
