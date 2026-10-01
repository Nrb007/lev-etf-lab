"""H-0003: hold the fund only during a window of calendar days each month."""

from __future__ import annotations

import pandas as pd


class MonthWindow:
    def __init__(self, start_day: int = 1, length: int = 5):
        self.name = f"month_window_{start_day}_{length}"
        self.params = {"start_day": start_day, "length": length}

    def compute(self, features: pd.DataFrame) -> pd.Series:
        day = pd.Series(features.index.day, index=features.index)
        start = self.params["start_day"]
        return ((day >= start) & (day < start + self.params["length"])).astype("float64")


def make_signal(**params):
    return MonthWindow(**params)
