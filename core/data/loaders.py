"""yfinance + FRED loaders with parquet caching (SPEC Section 4.1).

Live fetching is a manual, human-run path (`lab data pull`); tests inject recorded fixtures through
the ``fetch_price`` / ``fetch_rate`` parameters of :func:`pull`. Nothing is silently filled: every
missing session, forward-fill and dropped non-session date is recorded in the sidecar and logged.
"""

from __future__ import annotations

import io
import logging
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pandas as pd

from core.config import LabConfig, load_lab_config
from core.data import cache
from core.data.nyse import normalize_index, nyse_sessions
from core.data.splits import encrypt_holdout, split_dates, split_frame

log = logging.getLogger(__name__)

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
OPTIONAL_TICKERS = frozenset({"^VIX3M"})  # SPEC 4.1: "if available"

# Total-return prices: yfinance auto_adjust folds dividends and splits into Close.
ADJUSTMENT = {
    "method": "yfinance Ticker.history",
    "period": "max",
    "auto_adjust": True,
    "back_adjust": False,
    "repair": False,
    "actions": False,
    "field": "Close",
}

PriceFetcher = Callable[[str], pd.Series]
RateFetcher = Callable[[str], pd.Series]


@dataclass(frozen=True)
class FundSeries:
    """One closed-end fund's full-history series, aligned to each other by its theory loader.

    ``series`` maps each cache name (``cache.fund_series_names``) to its series; ``sources``
    describes where each came from; ``events`` is the loader's own alignment log. A session the
    loader dropped from all three stays absent: ``pull`` does not reindex these series to the
    calendar, so no NaN rows appear.
    """

    series: dict[str, pd.Series]
    sources: dict[str, str]
    events: list[dict]


FundFetcher = Callable[[str], FundSeries]


class FetchError(RuntimeError):
    """One or more required series could not be fetched."""


def fetch_yfinance(ticker: str) -> pd.Series:
    """Full available adjusted-close history for ``ticker`` (network)."""
    import yfinance as yf

    history = yf.Ticker(ticker).history(
        period=ADJUSTMENT["period"],
        auto_adjust=ADJUSTMENT["auto_adjust"],
        back_adjust=ADJUSTMENT["back_adjust"],
        repair=ADJUSTMENT["repair"],
        actions=ADJUSTMENT["actions"],
    )
    if history.empty:
        raise FetchError(f"yfinance returned no rows for {ticker}")
    close = history[ADJUSTMENT["field"]]
    close.index = normalize_index(close.index)
    return close.rename(ticker)


def fetch_fred(series: str) -> pd.Series:
    """Full FRED history for ``series`` from the public CSV endpoint, in percent (network)."""
    request = urllib.request.Request(
        FRED_URL.format(series=series), headers={"User-Agent": "lev-etf-lab"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed https URL
        text = response.read().decode()
    frame = pd.read_csv(io.StringIO(text), na_values=["."], parse_dates=[0])
    values = pd.Series(
        pd.to_numeric(frame.iloc[:, 1]).to_numpy(),
        index=normalize_index(pd.DatetimeIndex(frame.iloc[:, 0])),
    )
    return values.rename(cache.fred_name(series))


def align_to_calendar(
    series: pd.Series, name: str, fill: Literal["none", "ffill"] = "none"
) -> tuple[pd.Series, list[dict]]:
    """Reindex ``series`` to the NYSE sessions spanning its own valid range.

    Returns the aligned series and an event log. Missing sessions stay NaN unless ``fill="ffill"``
    (used for rate series that skip bond-market holidays); every fill and every dropped
    non-session date is recorded.
    """
    series = series.copy()
    series.index = normalize_index(series.index)
    series = series[~series.index.duplicated(keep="last")].sort_index().dropna()
    if series.empty:
        return series, []
    sessions = nyse_sessions(series.index[0], series.index[-1])
    events: list[dict] = []

    extra = series.index.difference(sessions)
    if len(extra):
        events.append(
            {
                "kind": "dropped_non_session",
                "count": int(len(extra)),
                "first": str(extra[0].date()),
                "last": str(extra[-1].date()),
            }
        )
        log.warning("%s: dropped %d dates that are not NYSE sessions", name, len(extra))

    aligned = series.reindex(sessions)
    missing = aligned.index[aligned.isna()]
    if fill == "ffill":
        aligned = aligned.ffill()
    for day in missing:
        kind = "forward_fill" if fill == "ffill" else "missing"
        events.append({"kind": kind, "date": str(day.date())})
    if len(missing):
        log.warning(
            "%s: %d NYSE sessions had no value (%s)",
            name,
            len(missing),
            "forward-filled" if fill == "ffill" else "left as NaN",
        )
    return aligned.rename(name), events


def universe_series(config: LabConfig) -> list[str]:
    """Every cache name the configured universe needs (tickers, then FRED series)."""
    u = config.universe
    tickers = [
        *u.underlyings,
        *u.leveraged_3x,
        *(f.ticker for f in u.loaded_not_used),
        *u.volatility,
    ]
    funds = [n for t in u.closed_end_funds for n in cache.fund_series_names(t)]
    return [
        *dict.fromkeys(tickers),
        *(cache.fred_name(r.series) for r in u.rates),
        *dict.fromkeys(funds),
    ]


def pull(
    config: LabConfig | None = None,
    *,
    refresh: bool = False,
    fetch_price: PriceFetcher = fetch_yfinance,
    fetch_rate: RateFetcher = fetch_fred,
    fetch_fund: FundFetcher | None = None,
    names: Sequence[str] | None = None,
    cache_dir: Path | None = None,
    holdout_path: Path | None = None,
    holdout_key: bytes | str | None = None,
) -> dict:
    """Fetch, align, split and cache the configured universe.

    Full history is fetched per series. Only the train slice is cached; the hold-out slice goes to
    ``holdout_path`` (Fernet-encrypted with ``holdout_key``) and only when every series was fetched
    in this run and a key was supplied. Existing cache entries are kept unless ``refresh``.

    A closed-end fund (``universe.closed_end_funds``) is three series fetched together by
    ``fetch_fund`` (a theory package's loader) and cached together: all three are kept or all three
    re-fetched. ``names`` restricts the run to those series; a restricted run never writes the
    hold-out file, which must always be built from the whole universe.
    """
    config = config or load_lab_config()
    directory = cache_dir or cache.cache_dir()
    holdout_path = holdout_path or cache.holdout_path()
    dates = split_dates(config)
    fetched_at = datetime.now(UTC).isoformat(timespec="seconds")
    names = universe_series(config) if names is None else list(names)
    restricted = set(names) != set(universe_series(config))
    fund_of = {n: t for t in config.universe.closed_end_funds for n in cache.fund_series_names(t)}
    group_cached = {
        t: all(cache.has_series(directory, n) for n in cache.fund_series_names(t))
        for t in config.universe.closed_end_funds
    }
    fund_fetched: dict[str, FundSeries] = {}

    status: dict[str, str] = {}
    errors: list[str] = []
    holdout_slices: dict[str, pd.Series] = {}

    for name in names:
        if name in fund_of:
            already = group_cached[fund_of[name]]
        else:
            already = cache.has_series(directory, name)
        if not refresh and already:
            status[name] = "cached"
            log.info("%s: cached, skipping (use --refresh to re-fetch)", name)
            continue
        rate = cache.is_rate(name)
        fund_events: list[dict] = []
        try:
            if name in fund_of:
                ticker = fund_of[name]
                if fetch_fund is None:
                    raise FetchError("no closed-end fund fetcher was supplied")
                if ticker not in fund_fetched:
                    fund_fetched[ticker] = fetch_fund(ticker)
                raw = fund_fetched[ticker].series[name]
                fund_events = fund_fetched[ticker].events
            elif rate:
                raw = fetch_rate(name.removeprefix(cache.FRED_PREFIX))
            else:
                raw = fetch_price(name)
        except Exception as exc:
            if name in OPTIONAL_TICKERS:
                status[name] = "unavailable_optional"
                log.warning("%s: optional series unavailable (%s)", name, exc)
            else:
                status[name] = "failed"
                errors.append(f"{name}: {exc}")
            continue

        fill: Literal["none", "ffill"] = "ffill" if rate else "none"
        raw = raw.copy()
        raw.index = normalize_index(raw.index)
        raw_train, raw_holdout = split_frame(raw.sort_index(), dates)
        if name in fund_of:
            train, holdout, events = raw_train.rename(name), raw_holdout.rename(name), []
        else:
            train, events = align_to_calendar(raw_train, name, fill=fill)
            holdout, _ = align_to_calendar(raw_holdout, name, fill=fill)
        holdout_slices[name] = holdout

        if name in fund_of:
            described = fund_fetched[fund_of[name]].sources[name]
            source = {"source": described}
            adjustment = {"note": described}
            events = [*fund_events, *events]
        elif rate:
            source = {"source": "FRED", "url": FRED_URL.format(series=name.split(":", 1)[1])}
            adjustment = {"note": "percent per annum, as published; no adjustment"}
        else:
            source = {"source": "yfinance"}
            adjustment = ADJUSTMENT
        cache.write_series(
            directory,
            name,
            train,
            {
                **source,
                "fetch_time": fetched_at,
                "adjustment": adjustment,
                "fill_policy": fill,
                "source_rows_fetched": int(len(raw)),
                "train_end_exclusive": str(dates.embargo_start.date()),
                "alignment_log": events,
            },
        )
        status[name] = "fetched"

    holdout_written = False
    fetched_all = all(s == "fetched" or s == "unavailable_optional" for s in status.values())
    if restricted:
        log.info("restricted pull: %s not written", holdout_path.name)
    elif holdout_slices and fetched_all and not errors:
        if holdout_key is None:
            log.warning("no hold-out key supplied; %s not written", holdout_path.name)
        else:
            encrypt_holdout(pd.concat(holdout_slices.values(), axis=1), holdout_key, holdout_path)
            holdout_written = True
    elif holdout_slices:
        log.warning("hold-out slice not updated: run with --refresh to rebuild it from scratch")

    if errors:
        raise FetchError("; ".join(errors))
    return {"series": status, "holdout_written": holdout_written, "fetched_at": fetched_at}
