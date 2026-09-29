from datetime import date

import pytest
from pydantic import ValidationError

from core.config import LabConfig, load_lab_config, load_thresholds


def test_lab_config_defaults():
    cfg = load_lab_config()
    assert cfg.holdout_start == date(2024, 7, 1)
    assert cfg.embargo_trading_days == 21
    assert cfg.cost_bps == 5
    u = cfg.universe
    assert u.underlyings == ["QQQ", "SOXX", "SMH"]
    assert u.leveraged_3x == ["TQQQ", "SOXL", "TECL"]
    assert {(f.ticker, f.leverage) for f in u.loaded_not_used} == {
        ("QLD", 2),
        ("SQQQ", -3),
        ("SOXS", -3),
    }
    assert u.volatility == ["^VIX", "^VIX3M"]
    assert [r.series for r in u.rates] == ["DFF", "DGS3MO"]


def test_thresholds_match_spec_table():
    t = load_thresholds()
    assert t.dsr.min_probability == 0.95
    assert t.spa.max_p_value == 0.05
    assert t.pbo.max_pbo == 0.30
    assert t.pbo.cscv_partitions == 16
    assert t.permutation.max_p_value == 0.05
    assert t.permutation.min_shifts == 5000
    assert t.sensitivity.perturbations == [0.2, 0.4]
    assert t.sensitivity.min_median_neighbor_sharpe_ratio == 0.6
    assert t.sensitivity.min_fraction_neighbors_beating_benchmark == 0.8
    assert t.stress.cost_multiplier == 3
    assert t.stress.financing_spread_bps == 200
    assert t.stress.min_excess_sharpe == 0
    assert t.regime.min_fraction_positive_regimes == 0.6
    assert t.regime.max_single_regime_share == 0.5
    assert t.holdout.min_excess_sharpe == 0


def test_unknown_key_rejected():
    with pytest.raises(ValidationError):
        LabConfig.model_validate({"cost_bps": 5, "bogus": 1})
