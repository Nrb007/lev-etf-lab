"""Price and NAV loader for closed-end funds.

Three series per fund go into the same parquet cache the core loaders use, each on one shared index
of NYSE sessions where the price and the NAV both exist:

- ``<TICKER>``      total-return price (adjusted close), the series that is traded and backtested;
- ``PX:<TICKER>``   the unadjusted close, as quoted;
- ``NAV:<TICKER>``  the unadjusted daily NAV, as published.

Premium or discount is ``PX / NAV - 1`` and needs the two *unadjusted* series, which are on the same
basis; the adjusted close is on a different basis (dividends folded in) and must not be divided by
NAV. A session missing from either source is dropped from all three and recorded in the sidecar's
``alignment_log``; nothing is filled.

This module only fetches and aligns. Splitting at ``holdout_start``, caching the train slice and
encrypting the hold-out slice is ``core.data.loaders.pull``'s job: a fund listed under
``universe.closed_end_funds`` in ``config/lab.yaml`` goes through the same path as every other
series. ``fetch_fund_series`` is the fetcher it is given, and ``pull_cef`` runs that path for chosen
funds alone (which never writes the hold-out file).

``load_cef`` is the only way for this package to read the cached series back.

Live fetching is a human-run path (``lab data cef``); tests inject recorded fixtures through the
``fetch_price`` / ``fetch_nav`` parameters.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import pandas as pd

from core.config import LabConfig, load_lab_config
from core.data import cache
from core.data.cache import nav_name, px_name
from core.data.loaders import FetchError, FundSeries, pull
from core.data.nyse import normalize_index, nyse_sessions
from core.data.splits import load_prices
from theories.cef.funds import CEFCONNECT_URL, FUNDS, CefFund

log = logging.getLogger(__name__)

MAX_ABS_PREMIUM = 0.6  # a wider premium or discount than this is a bad quote or NAV, not a market
MAX_DROPPED_SHARE = 0.01  # more sessions than this missing from either source is a failed fetch

PriceFetcher = Callable[[str], pd.DataFrame]  # symbol -> frame with "close" and "adj_close"
NavFetcher = Callable[[str], pd.Series]  # symbol -> NAV series


def fetch_yfinance_both(symbol: str) -> pd.DataFrame:
    """Unadjusted and adjusted daily closes for ``symbol`` (network)."""
    import yfinance as yf

    history = yf.Ticker(symbol).history(period="max", auto_adjust=False, actions=False)
    if history.empty:
        raise FetchError(f"yfinance returned no rows for {symbol}")
    adj = yf.Ticker(symbol).history(period="max", auto_adjust=True, actions=False)["Close"]
    frame = pd.DataFrame({"close": history["Close"], "adj_close": adj})
    frame.index = normalize_index(frame.index)
    return frame


def fetch_yfinance_nav(symbol: str) -> pd.Series:
    """A fund's published daily NAV from its Yahoo NAV symbol (network)."""
    import yfinance as yf

    history = yf.Ticker(symbol).history(period="max", auto_adjust=False, actions=False)
    if history.empty:
        raise FetchError(f"yfinance returned no NAV rows for {symbol}")
    nav = history["Close"]
    nav.index = normalize_index(nav.index)
    return nav.rename(symbol)


def fetch_cefconnect(ticker: str, period: str = "1Y") -> pd.DataFrame:
    """CEFConnect's price, NAV and discount for ``ticker``: an independent source for checks."""
    request = urllib.request.Request(
        CEFCONNECT_URL.format(ticker=ticker, period=period),
        headers={"User-Agent": "Mozilla/5.0 lev-etf-lab"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed https URL
        rows = json.loads(response.read())["Data"]["PriceHistory"]
    frame = pd.DataFrame(rows)
    frame.index = normalize_index(pd.DatetimeIndex(pd.to_datetime(frame["DataDate"])))
    return pd.DataFrame({"price": frame["Data"], "nav": frame["NAVData"]})


def _clean(series: pd.Series) -> pd.Series:
    series = series.copy()
    series.index = normalize_index(series.index)
    series = series[~series.index.duplicated(keep="last")].sort_index()
    return series.dropna()


def align_price_and_nav(
    close: pd.Series, adj_close: pd.Series, nav: pd.Series, ticker: str
) -> tuple[dict[str, pd.Series], list[dict]]:
    """Put the three series on the NYSE sessions where price and NAV both exist.

    Returns the aligned series and the event log. Raises ``FetchError`` for a premium outside
    ``MAX_ABS_PREMIUM`` or if too many sessions had to be dropped.
    """
    close, adj_close, nav = _clean(close), _clean(adj_close), _clean(nav)
    first = max(close.index[0], nav.index[0])
    last = min(close.index[-1], nav.index[-1])
    sessions = nyse_sessions(first, last)
    events: list[dict] = []
    for name, series in (("price", close), ("nav", nav)):
        extra = series.index.difference(sessions)
        extra = extra[(extra >= first) & (extra <= last)]
        if len(extra):
            events.append({"kind": "dropped_non_session", "source": name, "count": int(len(extra))})
    keep = sessions[sessions.isin(close.index) & sessions.isin(nav.index)]
    for day in sessions.difference(keep):
        source = "nav" if day in close.index else "price"
        events.append({"kind": "missing", "source": source, "date": str(day.date())})
    if len(sessions) and (len(sessions) - len(keep)) / len(sessions) > MAX_DROPPED_SHARE:
        raise FetchError(
            f"{ticker}: {len(sessions) - len(keep)} of {len(sessions)} sessions lack a price or a "
            "NAV; refusing to cache a series with that many gaps"
        )
    aligned = {
        "adj_close": adj_close.reindex(keep),
        "close": close.reindex(keep),
        "nav": nav.reindex(keep),
    }
    if any(s.isna().any() for s in aligned.values()):
        raise FetchError(f"{ticker}: the adjusted close is missing on a session with a price")
    premium = aligned["close"] / aligned["nav"] - 1
    if (premium.abs() > MAX_ABS_PREMIUM).any():
        day = premium.index[(premium.abs() > MAX_ABS_PREMIUM).to_numpy()][0]
        raise FetchError(f"{ticker}: premium {premium[day]:+.0%} on {day.date()} is not credible")
    for event in events:
        log.warning("%s: %s", ticker, event)
    return aligned, events


def fetch_fund_series(
    ticker: str,
    *,
    fetch_price: PriceFetcher = fetch_yfinance_both,
    fetch_nav: NavFetcher = fetch_yfinance_nav,
) -> FundSeries:
    """Fetch and align a registered fund's price and NAV.

    This is the fetcher ``core.data.loaders.pull`` is given for ``universe.closed_end_funds``.
    """
    fund: CefFund | None = FUNDS.get(ticker)
    if fund is None:
        raise FetchError(f"{ticker}: not a registered closed-end fund (theories/cef/funds.py)")
    prices = fetch_price(ticker)
    nav = fetch_nav(fund.nav_symbol)
    aligned, events = align_price_and_nav(prices["close"], prices["adj_close"], nav, ticker)
    return FundSeries(
        series={
            ticker: aligned["adj_close"],
            px_name(ticker): aligned["close"],
            nav_name(ticker): aligned["nav"],
        },
        sources={
            ticker: "yfinance Ticker.history auto_adjust=True (total-return close)",
            px_name(ticker): "yfinance Ticker.history auto_adjust=False (unadjusted close)",
            nav_name(ticker): f"yfinance NAV symbol {fund.nav_symbol} (unadjusted daily NAV)",
        },
        events=events,
    )


def pull_cef(
    tickers: list[str] | None = None,
    *,
    refresh: bool = False,
    config: LabConfig | None = None,
    fetch_price: PriceFetcher = fetch_yfinance_both,
    fetch_nav: NavFetcher = fetch_yfinance_nav,
    cache_dir: Path | None = None,
) -> dict:
    """Run ``core.data.loaders.pull`` for the chosen funds only.

    The funds must be registered here and listed under ``universe.closed_end_funds`` in the config,
    because the split at ``holdout_start`` and the hold-out slice are decided there. This path
    writes the train cache only; ``holdout.enc`` is rebuilt by a full ``lab data pull --refresh``.
    """
    config = config or load_lab_config()
    chosen = tickers or list(config.universe.closed_end_funds)
    unregistered = [t for t in chosen if t not in FUNDS]
    if unregistered:
        raise FetchError(
            f"{', '.join(unregistered)}: not a registered closed-end fund (theories/cef/funds.py)"
        )
    unlisted = [t for t in chosen if t not in config.universe.closed_end_funds]
    if unlisted:
        raise FetchError(
            f"{', '.join(unlisted)}: not under universe.closed_end_funds in config/lab.yaml"
        )
    result = pull(
        config,
        refresh=refresh,
        fetch_fund=lambda t: fetch_fund_series(t, fetch_price=fetch_price, fetch_nav=fetch_nav),
        names=[n for t in chosen for n in cache.fund_series_names(t)],
        cache_dir=cache_dir,
    )
    series = result["series"]
    return {
        "series": {t: series[t] for t in chosen},
        "fetched_at": result["fetched_at"],
    }


def load_cef(
    ticker: str,
    split: Literal["train"] = "train",
    *,
    cache_dir: Path | None = None,
    config: LabConfig | None = None,
) -> pd.DataFrame:
    """A fund's train-split series: ``adj_close``, ``close``, ``nav`` and ``premium``.

    The only reader of cached closed-end fund data in this package. It goes through
    ``core.data.splits.load_prices``, which reads the train cache and hard-truncates at the embargo
    start, so no row on or after it is returned whatever the cache holds. ``premium`` is
    ``close / nav - 1`` on the two unadjusted series.
    """
    if split != "train":
        raise ValueError(f"load_cef only serves split='train', got {split!r}")
    names = cache.fund_series_names(ticker)
    frame = load_prices(names, "train", cache_dir=cache_dir, config=config)
    out = frame.set_axis(["adj_close", "close", "nav"], axis=1)
    out["premium"] = out["close"] / out["nav"] - 1
    return out


def compare_with_cefconnect(
    ticker: str, *, fetch_nav: NavFetcher = fetch_yfinance_nav, other: pd.DataFrame | None = None
) -> dict:
    """Agreement between the Yahoo NAV and price and CEFConnect's over CEFConnect's last year."""
    fund = FUNDS[ticker]
    other = fetch_cefconnect(ticker) if other is None else other
    nav = _clean(fetch_nav(fund.nav_symbol)).reindex(other.index)
    both = pd.DataFrame({"yahoo": nav, "cefconnect": other["nav"]}).dropna()
    diff = (both["yahoo"] - both["cefconnect"]).abs()
    return {
        "ticker": ticker,
        "sessions_compared": int(len(both)),
        "sessions_without_yahoo_nav": int(nav.isna().sum()),
        "nav_exact_share": float((diff < 0.011).mean()) if len(both) else None,
        "nav_max_abs_diff": float(diff.max()) if len(both) else None,
    }
