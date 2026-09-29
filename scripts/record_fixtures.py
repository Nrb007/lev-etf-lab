"""Record the small committed fixtures used by the data-layer tests (live network; human-run).

    uv run python scripts/record_fixtures.py

Writes raw, unaligned series exactly as the fetchers return them to ``tests/fixtures/`` so the
tests exercise alignment and splitting without touching the network.
"""

from __future__ import annotations

from pathlib import Path

from core.data.loaders import fetch_fred, fetch_yfinance

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
START, END = "2018-06-01", "2019-12-31"
PRICES = ["QQQ", "TQQQ", "^VIX"]
RATES = ["DFF", "DGS3MO"]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name in PRICES:
        series = fetch_yfinance(name).loc[START:END]
        series.to_csv(OUT / f"{name.replace('^', 'IDX_')}.csv", header=["value"])
    for name in RATES:
        series = fetch_fred(name).loc[START:END]
        series.to_csv(OUT / f"FRED_{name}.csv", header=["value"])


if __name__ == "__main__":
    main()
