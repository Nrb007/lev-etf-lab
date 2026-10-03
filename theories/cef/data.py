"""Price and NAV loader for closed-end funds (train split only).

Three series per fund go into the same parquet cache the core loaders use, each on one shared index
of NYSE sessions where the price and the NAV both exist:

- ``<TICKER>``      total-return price (adjusted close), the series that is traded and backtested;
- ``PX:<TICKER>``   the unadjusted close, as quoted;
- ``NAV:<TICKER>``  the unadjusted daily NAV, as published.

Premium or discount is ``PX / NAV - 1`` and needs the two *unadjusted* series, which are on the same
basis; the adjusted close is on a different basis (dividends folded in) and must not be divided by
NAV. A session missing from either source is dropped from all three and recorded in the sidecar's
``alignment_log``; nothing is filled.

Only the train slice is cached. The hold-out slice of these series is not fetched into
``holdout.enc`` (SPEC Section 8): see ``core.judge_runner._require_holdout_series``.

Live fetching is a human-run path (``lab data cef``); tests inject recorded fixtures through the
``fetch_price`` / ``fetch_nav`` parameters.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from core.config import LabConfig, load_lab_config
from core.data import cache
from core.data.loaders import FetchError
from core.data.nyse import normalize_index, nyse_sessions
from core.data.splits import split_dates
from theories.cef.funds import CEFCONNECT_URL, FUNDS, CefFund

log = logging.getLogger(__name__)

MAX_ABS_PREMIUM = 0.6  # a wider premium or discount than this is a bad quote or NAV, not a market
MAX_DROPPED_SHARE = 0.01  # more sessions than this missing from either source is a failed fetch

PriceFetcher = Callable[[str], pd.DataFrame]  # symbol -> frame with "close" and "adj_close"
NavFetcher = Callable[[str], pd.Series]  # symbol -> NAV series


def px_name(ticker: str) -> str:
    return f"PX:{ticker}"


def nav_name(ticker: str) -> str:
    return f"NAV:{ticker}"


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


def pull_cef(
    tickers: list[str] | None = None,
    *,
    refresh: bool = False,
    config: LabConfig | None = None,
    fetch_price: PriceFetcher = fetch_yfinance_both,
    fetch_nav: NavFetcher = fetch_yfinance_nav,
    cache_dir: Path | None = None,
) -> dict:
    """Fetch, align, truncate to the train split and cache each fund's three series."""
    config = config or load_lab_config()
    directory = cache_dir or cache.cache_dir()
    train_end = split_dates(config).embargo_start
    fetched_at = datetime.now(UTC).isoformat(timespec="seconds")
    status: dict[str, str] = {}
    errors: list[str] = []
    for ticker in tickers or list(FUNDS):
        fund: CefFund | None = FUNDS.get(ticker)
        if fund is None:
            errors.append(f"{ticker}: not a registered closed-end fund (theories/cef/funds.py)")
            continue
        if not refresh and all(
            cache.has_series(directory, n) for n in (ticker, px_name(ticker), nav_name(ticker))
        ):
            status[ticker] = "cached"
            continue
        try:
            prices = fetch_price(ticker)
            nav = fetch_nav(fund.nav_symbol)
            aligned, events = align_price_and_nav(prices["close"], prices["adj_close"], nav, ticker)
        except Exception as exc:
            status[ticker] = "failed"
            errors.append(f"{ticker}: {exc}")
            continue
        meta = {
            "fetch_time": fetched_at,
            "fill_policy": "none",
            "train_end_exclusive": str(train_end.date()),
            "alignment_log": events,
            "theory": "cef",
        }
        sources = {
            ticker: ("yfinance Ticker.history auto_adjust=True", "adj_close"),
            px_name(ticker): ("yfinance Ticker.history auto_adjust=False", "close"),
            nav_name(ticker): (f"yfinance NAV symbol {fund.nav_symbol}, auto_adjust=False", "nav"),
        }
        for name, (source, column) in sources.items():
            series = aligned[column]
            series = series[series.index < train_end]
            cache.write_series(
                directory, name, series, {**meta, "source": source, "adjustment": source}
            )
        status[ticker] = "fetched"
    if errors:
        raise FetchError("; ".join(errors))
    return {"series": status, "fetched_at": fetched_at}


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
