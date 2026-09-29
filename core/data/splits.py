"""Train / hold-out separation (SPEC Section 4.3).

``load_prices(..., split="train")`` is the only loader hypothesis code may use. It reads the
train-only cache and additionally hard-truncates at the embargo start, so it cannot return a row
on or after ``holdout_start`` (or inside the embargo) whatever the cache contains.

Only ``core/judge/holdout.py`` may call ``decrypt_holdout``.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pandas as pd
from cryptography.fernet import Fernet

from core.config import LabConfig, load_lab_config
from core.data import cache
from core.data.nyse import nyse_sessions


@dataclass(frozen=True)
class SplitDates:
    """Train covers dates < embargo_start; hold-out covers dates >= holdout_start.

    The ``embargo_trading_days`` sessions in [embargo_start, holdout_start) belong to neither side.
    """

    embargo_start: pd.Timestamp
    holdout_start: pd.Timestamp


def split_dates(config: LabConfig | None = None) -> SplitDates:
    config = config or load_lab_config()
    holdout_start = pd.Timestamp(config.holdout_start)
    n = config.embargo_trading_days
    if n == 0:
        return SplitDates(embargo_start=holdout_start, holdout_start=holdout_start)
    window_start = holdout_start - pd.Timedelta(days=2 * n + 30)
    sessions = nyse_sessions(window_start, holdout_start - pd.Timedelta(days=1))
    if len(sessions) < n:
        raise RuntimeError("calendar window too short to place the embargo")
    return SplitDates(embargo_start=sessions[-n], holdout_start=holdout_start)


def split_frame(
    frame: pd.DataFrame | pd.Series, dates: SplitDates
) -> tuple[pd.DataFrame | pd.Series, pd.DataFrame | pd.Series]:
    """Return (train, holdout); embargo rows are dropped from both."""
    train = frame[frame.index < dates.embargo_start]
    holdout = frame[frame.index >= dates.holdout_start]
    return train, holdout


def load_prices(
    tickers: str | Sequence[str],
    split: Literal["train"] = "train",
    *,
    cache_dir: Path | None = None,
    config: LabConfig | None = None,
) -> pd.DataFrame:
    """Train-split adjusted closes (or rates, for ``FRED:<id>`` names), one column per name."""
    if split != "train":
        raise ValueError(f"load_prices only serves split='train', got {split!r}")
    names = [tickers] if isinstance(tickers, str) else list(tickers)
    directory = cache_dir or cache.cache_dir()
    dates = split_dates(config)
    frame = pd.concat([cache.read_series(directory, n) for n in names], axis=1)
    frame = frame[frame.index < dates.embargo_start]  # hard truncation, independent of the cache
    return frame


def encrypt_holdout(frame: pd.DataFrame, key: bytes | str, path: Path) -> None:
    """Write the hold-out slice to ``path`` as Fernet-encrypted parquet."""
    buffer = io.BytesIO()
    frame.to_parquet(buffer)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(Fernet(key).encrypt(buffer.getvalue()))


def decrypt_holdout(path: Path, key: bytes | str) -> pd.DataFrame:
    """Decrypt the hold-out slice. Reserved for ``core/judge/holdout.py``."""
    return pd.read_parquet(io.BytesIO(Fernet(key).decrypt(path.read_bytes())))
