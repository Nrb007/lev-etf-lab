"""H-0001: hold the fund when the underlying's trailing return is above a hurdle."""

from __future__ import annotations

import pandas as pd


class TrailingReturn:
    def __init__(self, window: int = 5, hurdle: float = 0.0):
        self.name = f"trailing_return_{window}_{hurdle:g}"
        self.params = {"window": window, "hurdle": hurdle}

    def compute(self, features: pd.DataFrame) -> pd.Series:
        window = max(1, int(round(self.params["window"])))
        trailing = features["underlying"].astype("float64").pct_change(window)
        return (trailing > self.params["hurdle"]).astype("float64").where(trailing.notna())


def make_signal(**params):
    return TrailingReturn(**params)
