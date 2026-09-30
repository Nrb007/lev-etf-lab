"""H-0001: scale exposure down when trailing realized vol makes leveraged vol drag expensive."""

from __future__ import annotations

import numpy as np
import pandas as pd


class VolTargetDrag:
    def __init__(self, lookback: int = 20, target_vol: float = 0.5):
        self.name = f"voltarget_drag_{lookback}_{target_vol:g}"
        self.params = {"lookback": lookback, "target_vol": target_vol}

    def compute(self, features: pd.DataFrame) -> pd.Series:
        close = features["close"].astype("float64")
        ret = close.pct_change()
        n = int(self.params["lookback"])
        # annualized trailing realized vol of the fund itself, using rows up to and including t
        vol = ret.rolling(n).std() * np.sqrt(252.0)
        pos = (self.params["target_vol"] / vol).clip(lower=0.0, upper=1.0)
        return pos.where(vol.notna() & (vol > 0))


def make_signal(**params):
    return VolTargetDrag(**params)
