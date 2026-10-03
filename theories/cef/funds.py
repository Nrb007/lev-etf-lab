"""The closed-end funds this package can load, and where each fund's daily NAV comes from.

The NAV source is Yahoo Finance's per-fund NAV symbol, read with the same ``yfinance`` call as the
fund's price. Checked 2026-10-03: ADX, GAB, USA, PDI, BST and EOS each have one (``X`` + ticker +
``X``), with daily history from 1999 to 2012 onward; CET's guessed symbol does not exist, so the
pattern is a convention to verify per fund, not a rule. For ADX the last year of NAV matched
CEFConnect's published NAV on 243 of 244 sessions (docs/decisions.md).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CefFund:
    ticker: str
    nav_symbol: str  # Yahoo symbol of the fund's daily NAV
    name: str


FUNDS: dict[str, CefFund] = {
    "ADX": CefFund("ADX", "XADEX", "Adams Diversified Equity Fund"),
}

CEFCONNECT_URL = "https://www.cefconnect.com/api/v3/pricinghistory/{ticker}/{period}"
