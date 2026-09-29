"""Throwaway signals that exist only to exercise the engine (not hypotheses; see M2 decisions)."""

from __future__ import annotations

import pandas as pd


class ConstantSignal:
    """Hold a fixed exposure every day."""

    def __init__(self, exposure: float = 1.0):
        self.name = f"constant_{exposure:g}"
        self.params = {"exposure": exposure}

    def compute(self, features: pd.DataFrame) -> pd.Series:
        return pd.Series(self.params["exposure"], index=features.index, dtype="float64")


class MovingAverageCrossover:
    """Long when the close is above its trailing mean (uses the close of day t only)."""

    def __init__(self, window: int = 10):
        self.name = f"ma_cross_{window}"
        self.params = {"window": window}

    def compute(self, features: pd.DataFrame) -> pd.Series:
        close = features["close"]
        mean = close.rolling(self.params["window"]).mean()
        return (close > mean).astype("float64").where(mean.notna())


class TomorrowPeek:
    """LEAKY: long when tomorrow's close is higher. Uses a future row."""

    name = "tomorrow_peek"
    params: dict = {}

    def compute(self, features: pd.DataFrame) -> pd.Series:
        close = features["close"]
        return (close.shift(-1) > close).astype("float64").where(close.shift(-1).notna(), 0.0)


class FullSampleZScore:
    """LEAKY: normalizes by the whole-sample mean, so early values move when data is removed."""

    name = "full_sample_zscore"
    params: dict = {}

    def compute(self, features: pd.DataFrame) -> pd.Series:
        close = features["close"]
        return (close > close.mean()).astype("float64")


class ScriptedSignal:
    """Return a precomputed position series (for exact timing and contract tests)."""

    def __init__(self, positions: pd.Series, name: str = "scripted"):
        self.name = name
        self.params: dict = {}
        self._positions = positions

    def compute(self, features: pd.DataFrame) -> pd.Series:
        return self._positions.reindex(features.index)
