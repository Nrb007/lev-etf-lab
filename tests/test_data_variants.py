"""Synthetic leverage and inverse variants of each underlying, and the real-fund cross-checks."""

import json

import pytest

from core.config import LabConfig
from core.data import cache
from core.data.splits import load_prices
from core.data.synthetic import (
    LEVERAGE_FACTORS,
    daily_returns,
    synthetic_fund_prices,
    synthetic_returns,
    variant_key,
)
from core.data.variants import build_variants


def config_with(loaded_not_used, underlyings=("QQQ",)) -> LabConfig:
    return LabConfig.model_validate(
        {
            "universe": {
                "underlyings": list(underlyings),
                "leveraged_3x": ["TQQQ"],
                "loaded_not_used": loaded_not_used,
                "volatility": ["^VIX", "^VIX3M"],
                "rates": [
                    {"source": "FRED", "series": "DFF"},
                    {"source": "FRED", "series": "DGS3MO"},
                ],
            },
            "holdout_start": "2019-10-01",
            "embargo_trading_days": 21,
            "cost_bps": 5,
        }
    )


def test_factor_set_covers_the_section_15_variants():
    assert {1, 2, -1, -2, -3} <= set(LEVERAGE_FACTORS) and 3 in LEVERAGE_FACTORS


def test_every_factor_is_cached_under_its_own_key_with_a_sidecar(pulled, tmp_path):
    out = tmp_path / "validation.json"
    result = build_variants(config=config_with([]), cache_dir=pulled["cache_dir"], out_path=out)
    assert [v["leverage"] for v in result["variants"]] == list(LEVERAGE_FACTORS)
    assert result["validations"] == [] and not out.exists()
    for factor in LEVERAGE_FACTORS:
        key = variant_key("QQQ", factor)
        assert cache.has_series(pulled["cache_dir"], key)
        stored = cache.read_series(pulled["cache_dir"], key)
        meta = cache.read_meta(pulled["cache_dir"], key)
        assert meta["leverage"] == factor and meta["underlying"] == "QQQ"
        assert stored.iloc[0] > 0 and len(stored) > 100
    assert variant_key("QQQ", -2) == "SYNTH:QQQ:-2x"


def test_one_x_variant_tracks_the_underlying_less_the_fee(pulled):
    kw = dict(cache_dir=pulled["cache_dir"], config=config_with([]))
    one = daily_returns(synthetic_fund_prices("QQQ", 1, **kw)).dropna()
    under = daily_returns(load_prices("QQQ", "train", **kw)["QQQ"].dropna()).reindex(one.index)
    assert (under - one).mean() == pytest.approx(0.0095 / 252, rel=1e-6)


def test_inverse_variant_moves_against_the_underlying(pulled):
    kw = dict(cache_dir=pulled["cache_dir"], config=config_with([]))
    inverse = daily_returns(synthetic_fund_prices("QQQ", -1, **kw)).dropna()
    under = daily_returns(load_prices("QQQ", "train", **kw)["QQQ"].dropna()).reindex(inverse.index)
    assert inverse.corr(under) < -0.999


def test_real_funds_in_the_cache_are_cross_checked_and_recorded(pulled, tmp_path):
    # Stand in for QLD with a fund that follows the 2x formula closely (not a real QLD).
    kw = dict(cache_dir=pulled["cache_dir"], config=config_with([]))
    under = daily_returns(load_prices("QQQ", "train", **kw)["QQQ"].dropna())
    dff = load_prices("FRED:DFF", "train", **kw)["FRED:DFF"]
    fake = synthetic_returns(under, dff, 2, expense_ratio=0.0095, financing_spread=0.006)
    prices = (100 * (1 + fake.dropna()).cumprod()).rename("QLD")
    cache.write_series(pulled["cache_dir"], "QLD", prices, {"source": "test"})
    out = tmp_path / "validation.json"
    result = build_variants(
        config=config_with(
            [
                {"ticker": "QLD", "leverage": 2},
                {"ticker": "SQQQ", "leverage": -3},  # not in the cache: skipped, not filled in
                {"ticker": "SOXS", "leverage": -3},  # underlying SOXX not configured: skipped
            ]
        ),
        cache_dir=pulled["cache_dir"],
        out_path=out,
    )
    qld, sqqq, soxs = result["validations"]
    assert qld["correlation_target_met"] and qld["daily_return_correlation"] > 0.99999
    assert "not in the cache" in sqqq["skipped"]
    assert "not in the configured universe" in soxs["skipped"]
    assert set(json.loads(out.read_text())) == {"QLD_2x"}
