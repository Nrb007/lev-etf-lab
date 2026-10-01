#!/usr/bin/env python3
"""Write a simulated demo universe into a cache directory (Milestone 6 dashboard demo).

    LAB_DATA_DIR=demo/data uv run python scripts/build_demo_world.py

The demo pipeline run (docs/evidence/m6/) needs a hypothesis that genuinely reaches ``advance``
and ones that are genuinely rejected, without touching the real ledger or registering a real
hypothesis. A long real-data sample cannot promise that, so the demo runs on a simulated universe
with the same tickers and calendar as the real one and a *planted* structure:

* ``^VIX`` is a log-AR(1) series that carries no information about returns, so VIX-level signals
  have nothing to find.
* QQQ returns have persistent momentum: the expected return is proportional to an exponentially
  weighted average of past returns (memory of about ten days) in every year, so a trailing-return
  signal over a range of windows has a real, known edge that is spread across years and VIX
  regimes.
* Everything else is noise. TQQQ is the synthetic 3x fund built from QQQ with the project's own
  ``synthetic_returns`` (financing at DFF plus spread, expense ratio).

Nothing here is market data and nothing built on it is a research finding: the dashboard labels
the demo accordingly. The train-period rows only are written (the hold-out slice is never
simulated, so the demo never scores a hold-out).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.data import cache  # noqa: E402
from core.data.nyse import nyse_sessions  # noqa: E402
from core.data.splits import split_dates  # noqa: E402
from core.data.synthetic import synthetic_returns  # noqa: E402

SEED = 20260930
START = "2010-02-11"
PHI = 0.97  # persistence of the log-VIX state
MU_Q = 0.0003  # daily drift of the underlying
SIGMA_Q = 0.012  # daily vol of the underlying
TREND_GAIN = 0.8  # expected return = gain * EWMA of past returns (a persistent trend)
TREND_DECAY = 0.9  # EWMA decay: the trend has a memory of about ten trading days
SOURCE = "simulated-demo-world"


def simulate(dates: pd.DatetimeIndex, seed: int = SEED) -> dict[str, pd.Series]:
    rng = np.random.default_rng(seed)
    n = len(dates)
    x = np.empty(n)
    x[0] = rng.standard_normal()
    shocks = rng.standard_normal(n) * np.sqrt(1 - PHI**2)
    for i in range(1, n):
        x[i] = PHI * x[i - 1] + shocks[i]
    vix = np.exp(2.95 + 0.30 * x)
    eps = rng.standard_normal(n)
    ret = np.zeros(n)
    trend = 0.0
    for i in range(1, n):
        ret[i] = MU_Q + TREND_GAIN * trend + SIGMA_Q * eps[i]
        trend = TREND_DECAY * trend + (1 - TREND_DECAY) * ret[i]
    qqq = pd.Series(50.0 * np.cumprod(1 + ret), index=dates)
    qqq.iloc[0] = 50.0
    years = dates.year + (dates.dayofyear - 1) / 365.0
    dff = pd.Series(
        np.interp(
            years, [2010, 2016, 2019, 2020, 2022, 2023.5, 2025], [0.1, 0.4, 2.3, 0.1, 0.1, 5.3, 5.3]
        ),
        index=dates,
    )
    dgs3mo = (dff + 0.05).rename("dgs3mo")
    fund_ret = synthetic_returns(qqq.pct_change().fillna(0.0), dff, 3)
    tqqq = pd.Series(100.0 * np.cumprod(1 + fund_ret.to_numpy()), index=dates)
    tqqq.iloc[0] = 100.0
    return {
        "QQQ": qqq,
        "TQQQ": tqqq,
        "^VIX": pd.Series(vix, index=dates),
        cache.fred_name("DFF"): dff,
        cache.fred_name("DGS3MO"): dgs3mo,
    }


def main() -> None:
    embargo_start = split_dates().embargo_start
    dates = nyse_sessions(START, embargo_start - pd.Timedelta(days=1))
    directory = cache.cache_dir()
    meta = {"source": SOURCE, "seed": SEED, "fetch_time": None, "simulated": True}
    for name, series in simulate(dates).items():
        cache.write_series(directory, name, series, meta)
    print(
        f"wrote {len(dates)} simulated sessions ({dates[0].date()} to {dates[-1].date()}) "
        f"for {len(simulate(dates))} series to {directory}"
    )


if __name__ == "__main__":
    main()
