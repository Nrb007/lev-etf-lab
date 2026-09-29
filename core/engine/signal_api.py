"""Signal interface (SPEC Section 5.1).

A signal turns a features frame into a target position per date. The value at date ``t`` may use
only information available at the close of ``t``; the engine, not the signal, applies it to the
next trading day's return (``core.engine.backtest``).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np
import pandas as pd

# The contract allows shorts from the start even though v1 hypotheses stay in [0, 1].
POSITION_MIN = -1.0
POSITION_MAX = 1.0


class SignalError(ValueError):
    """A signal returned something outside the Signal contract."""


@runtime_checkable
class Signal(Protocol):
    name: str
    params: dict

    def compute(self, features: pd.DataFrame) -> pd.Series:
        """Target position in [-1, 1] (v1: [0, 1]), indexed by date.

        Must use only information available at the close of that date.
        """
        ...


def compute_positions(signal: Signal, features: pd.DataFrame) -> pd.Series:
    """Run ``signal`` and enforce the output contract.

    Leading NaNs (indicator warm-up) mean "no position yet" and become 0. A NaN after the first
    valid value is an error: silently filling it would hide a data or signal bug.
    """
    positions = signal.compute(features)
    if not isinstance(positions, pd.Series):
        raise SignalError(f"{signal.name}: compute() must return a pandas Series")
    if not positions.index.equals(features.index):
        raise SignalError(f"{signal.name}: positions must be indexed like the features frame")
    positions = positions.astype("float64")
    valid = positions.notna()
    if valid.any():
        first = int(np.argmax(valid.to_numpy()))
        gaps = positions.iloc[first:].isna()
        if gaps.any():
            day = positions.iloc[first:].index[gaps.to_numpy()][0].date()
            raise SignalError(f"{signal.name}: NaN position on {day} after the signal started")
    positions = positions.fillna(0.0)
    bad = (positions < POSITION_MIN) | (positions > POSITION_MAX) | ~np.isfinite(positions)
    if bad.any():
        at = int(np.argmax(bad.to_numpy()))
        raise SignalError(
            f"{signal.name}: position {positions.iloc[at]:g} on {positions.index[at].date()} "
            f"is outside "
            f"[{POSITION_MIN:g}, {POSITION_MAX:g}]"
        )
    return positions.rename(signal.name)
