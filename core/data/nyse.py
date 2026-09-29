"""NYSE trading calendar helpers (SPEC Section 4.1)."""

from __future__ import annotations

from functools import cache

import pandas as pd
import pandas_market_calendars as mcal


@cache
def _calendar():
    return mcal.get_calendar("NYSE")


def normalize_index(index: pd.Index) -> pd.DatetimeIndex:
    """Tz-naive, midnight-normalized, nanosecond-resolution DatetimeIndex named ``date``."""
    idx = pd.DatetimeIndex(index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    return idx.normalize().as_unit("ns").rename("date")


def nyse_sessions(start, end) -> pd.DatetimeIndex:
    """NYSE trading sessions in [start, end], as a tz-naive index named ``date``."""
    days = _calendar().valid_days(start_date=pd.Timestamp(start), end_date=pd.Timestamp(end))
    return normalize_index(days)
