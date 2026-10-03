"""Leverage and inverse-fund variants of each underlying (SPEC Section 15).

Real funds exist at only a few leverage levels, so the 1x, 2x, 3x, -1x, -2x and -3x versions of
every configured underlying are synthesized with the Section 4.2 builder and cached as
``SYNTH:<underlying>:<L>x``. Where a real fund is already loaded (the ``loaded_not_used`` entries
of ``config/lab.yaml``: QLD, SQQQ, SOXS) the synthetic series is also checked against it with
``validate_against_real``, which records the result in ``results/data_validation.json``.
"""

from __future__ import annotations

from pathlib import Path

from core.config import LabConfig, load_lab_config
from core.data import cache
from core.data.splits import load_prices
from core.data.synthetic import (
    DEFAULT_EXPENSE_RATIO,
    DEFAULT_FINANCING_SPREAD,
    FUND_UNDERLYING,
    LEVERAGE_FACTORS,
    daily_returns,
    synthetic_fund_prices,
    validate_against_real,
    variant_key,
)


def build_variants(
    *,
    factors: tuple[float, ...] = LEVERAGE_FACTORS,
    config: LabConfig | None = None,
    cache_dir: Path | None = None,
    out_path: Path | None = None,
) -> dict:
    """Cache every (underlying, factor) variant and cross-check against the loaded real funds.

    Returns ``{"variants": [...], "validations": [...]}``. A real fund whose underlying is not in
    the configured universe, or that is not in the cache, is reported as skipped, never filled in.
    """
    config = config or load_lab_config()
    directory = cache_dir or cache.cache_dir()
    variants = []
    for underlying in config.universe.underlyings:
        for factor in factors:
            prices = synthetic_fund_prices(
                underlying, factor, cache_dir=directory, config=config
            ).rename(variant_key(underlying, factor))
            meta = {
                "research_universe": "synthetic_long",
                "underlying": underlying,
                "leverage": factor,
                "financing_spread": DEFAULT_FINANCING_SPREAD,
                "expense_ratio": DEFAULT_EXPENSE_RATIO,
                "source": "core.data.synthetic",
                "fetch_time": None,
            }
            cache.write_series(directory, variant_key(underlying, factor), prices, meta)
            variants.append({"underlying": underlying, "leverage": factor, "rows": len(prices)})

    validations = []
    for fund in config.universe.loaded_not_used:
        underlying = FUND_UNDERLYING.get(fund.ticker)
        entry = {"fund": fund.ticker, "underlying": underlying, "leverage": fund.leverage}
        if underlying not in config.universe.underlyings:
            validations.append({**entry, "skipped": "underlying not in the configured universe"})
            continue
        if not cache.has_series(directory, fund.ticker):
            validations.append({**entry, "skipped": f"{fund.ticker} is not in the cache"})
            continue
        prices = synthetic_fund_prices(
            underlying, fund.leverage, cache_dir=directory, config=config
        )
        real = load_prices(fund.ticker, "train", cache_dir=directory, config=config)[fund.ticker]
        meta = {
            "research_universe": "synthetic_long",
            "fund": fund.ticker,
            "underlying": underlying,
            "leverage": fund.leverage,
            "financing_spread": DEFAULT_FINANCING_SPREAD,
            "expense_ratio": DEFAULT_EXPENSE_RATIO,
        }
        result = validate_against_real(daily_returns(prices), real, meta=meta, out_path=out_path)
        validations.append(
            {
                **entry,
                "daily_return_correlation": result["daily_return_correlation"],
                "correlation_target_met": result["correlation_target_met"],
                "tracking_error_annualized": result["tracking_error_annualized"],
                "overlap_days": result["overlap"]["days"],
            }
        )
    return {"variants": variants, "validations": validations}
