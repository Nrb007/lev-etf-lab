"""Parquet cache with a metadata sidecar (SPEC Section 4.1).

Each cached series is ``<key>.parquet`` (one ``value`` column indexed by NYSE session date) plus
``<key>.meta.json`` recording source, fetch time, row count, content hash and the exact adjustment
settings. The cache holds train-period data only; see ``core.data.splits``.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
FRED_PREFIX = "FRED:"


class CacheMissError(FileNotFoundError):
    """A requested series is not in the cache."""


class CacheCorruptError(RuntimeError):
    """A cached parquet no longer matches the content hash in its sidecar."""


def data_dir() -> Path:
    return Path(os.environ.get("LAB_DATA_DIR") or REPO_ROOT / "data")


def cache_dir() -> Path:
    return data_dir() / "cache"


def holdout_path() -> Path:
    return data_dir() / "holdout.enc"


def results_dir() -> Path:
    return Path(os.environ.get("LAB_RESULTS_DIR") or REPO_ROOT / "results")


def fred_name(series: str) -> str:
    return f"{FRED_PREFIX}{series}"


def is_rate(name: str) -> bool:
    return name.startswith(FRED_PREFIX)


def px_name(ticker: str) -> str:
    """Cache name of a fund's unadjusted close, as quoted."""
    return f"PX:{ticker}"


def nav_name(ticker: str) -> str:
    """Cache name of a fund's unadjusted daily NAV, as published."""
    return f"NAV:{ticker}"


def fund_series_names(ticker: str) -> list[str]:
    """The three cache names a closed-end fund is stored under (adjusted close, quote, NAV)."""
    return [ticker, px_name(ticker), nav_name(ticker)]


def series_key(name: str) -> str:
    """Filesystem-safe cache key: ``^VIX`` -> ``IDX_VIX``, ``FRED:DFF`` -> ``FRED_DFF``."""
    return name.replace("^", "IDX_").replace(":", "_")


def content_hash(series: pd.Series) -> str:
    hashed = pd.util.hash_pandas_object(series.astype("float64"), index=True)
    return hashlib.sha256(hashed.to_numpy().tobytes()).hexdigest()


def _paths(directory: Path, name: str) -> tuple[Path, Path]:
    key = series_key(name)
    return directory / f"{key}.parquet", directory / f"{key}.meta.json"


def write_series(directory: Path, name: str, series: pd.Series, meta: dict) -> dict:
    """Write ``series`` and its sidecar; fills in row_count, content_hash and date range."""
    directory.mkdir(parents=True, exist_ok=True)
    parquet, sidecar = _paths(directory, name)
    series = series.astype("float64").rename("value")
    meta = {
        **meta,
        "name": name,
        "row_count": int(len(series)),
        "first_date": str(series.index[0].date()) if len(series) else None,
        "last_date": str(series.index[-1].date()) if len(series) else None,
        "content_hash": content_hash(series),
    }
    series.to_frame().to_parquet(parquet)
    sidecar.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    return meta


def has_series(directory: Path, name: str) -> bool:
    parquet, sidecar = _paths(directory, name)
    return parquet.exists() and sidecar.exists()


def read_meta(directory: Path, name: str) -> dict:
    _, sidecar = _paths(directory, name)
    if not sidecar.exists():
        raise CacheMissError(f"{name}: no cache sidecar in {directory}; run `lab data pull`")
    return json.loads(sidecar.read_text())


def read_series(directory: Path, name: str, *, verify: bool = True) -> pd.Series:
    """Read a cached series, failing loudly if it no longer matches its recorded hash."""
    parquet, _ = _paths(directory, name)
    if not has_series(directory, name):
        raise CacheMissError(f"{name}: not cached in {directory}; run `lab data pull`")
    series = pd.read_parquet(parquet)["value"].rename(name)
    if verify:
        expected = read_meta(directory, name)["content_hash"]
        if content_hash(series.rename("value")) != expected:
            raise CacheCorruptError(f"{name}: cached data does not match its sidecar hash")
    return series


def cached_names(directory: Path) -> list[str]:
    """Names of every series with a sidecar in ``directory``."""
    if not directory.exists():
        return []
    return sorted(json.loads(p.read_text())["name"] for p in directory.glob("*.meta.json"))
