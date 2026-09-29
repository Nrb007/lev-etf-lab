import json

import numpy as np
import pandas as pd
import pytest

from core.data import cache
from core.data.nyse import nyse_sessions
from core.data.validate import DataQualityError, check_series, run_validation

SESSIONS = nyse_sessions("2019-01-02", "2019-06-28")


def _prices(seed=0, **overrides):
    rng = np.random.default_rng(seed)
    s = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.01, len(SESSIONS))), index=SESSIONS)
    for pos, value in overrides.items():
        s.iloc[int(pos[1:])] = value
    return s


def _checks(report):
    return {(i["severity"], i["check"]) for i in report["issues"]}


def test_clean_series_has_no_issues():
    report = check_series("QQQ", _prices())
    assert report["issues"] == []
    assert report["missing_days"]["count"] == 0


def test_missing_days_warn_then_error_past_one_percent():
    one = _prices()
    one.iloc[10] = np.nan
    assert _checks(check_series("QQQ", one)) == {("warning", "missing_days")}
    many = _prices()
    many.iloc[10:20] = np.nan
    assert ("error", "missing_days") in _checks(check_series("QQQ", many))


@pytest.mark.parametrize("bad", [0.0, -5.0])
def test_non_positive_price_is_a_hard_error(bad):
    report = check_series("QQQ", _prices(p20=bad))
    assert ("error", "non_positive_prices") in _checks(report)
    assert report["non_positive_prices"]["count"] == 1


def test_outlier_thresholds_flag_at_40_and_error_at_80():
    base = _prices()
    flagged = base.copy()
    flagged.iloc[30:] *= 1.5  # +50% day: flagged, not an error
    assert _checks(check_series("TQQQ", flagged)) == {("warning", "return_outliers")}
    hard = base.copy()
    hard.iloc[30:] *= 0.1  # -90% day: hard error
    report = check_series("TQQQ", hard)
    assert ("error", "return_outliers") in _checks(report)
    assert report["return_outliers"]["hard_count"] == 1
    calm = base.copy()
    calm.iloc[30:] *= 1.35  # +35%: under the flag threshold
    assert check_series("TQQQ", calm)["issues"] == []


def test_volatility_index_spikes_warn_but_never_error():
    vix = _prices()
    vix.iloc[30:] *= 2.2  # +120% day, as on 2018-02-05
    report = check_series("^VIX", vix)
    assert _checks(report) == {("warning", "return_outliers")}
    assert report["return_outliers"]["hard_count"] == 1
    assert report["return_outliers"]["hard_threshold_enforced"] is False


def test_reverse_split_shaped_jump_is_reported():
    s = _prices()
    s.iloc[40:] *= 0.5  # looks like an unadjusted 2:1 split
    report = check_series("SOXS", s)
    assert report["suspected_splits"][0]["ratio_like"] == 2
    assert ("warning", "suspected_splits") in _checks(report)


def test_stale_prices_warn_at_five_and_error_at_twenty():
    short = _prices()
    short.iloc[50:56] = short.iloc[50]
    assert ("warning", "stale_prices") in _checks(check_series("QQQ", short))
    long = _prices()
    long.iloc[50:75] = long.iloc[50]
    report = check_series("QQQ", long)
    assert ("error", "stale_prices") in _checks(report)
    assert report["stale_prices"]["longest"] == 25


def test_rate_series_only_check_missing_days():
    rates = pd.Series(2.0, index=SESSIONS)  # flat and zero-return-free: no price checks apply
    report = check_series("FRED:DFF", rates)
    assert report["issues"] == []
    assert "return_outliers" not in report


def test_returns_are_not_evaluated_across_missing_days():
    s = _prices()
    s.iloc[20] = np.nan
    s.iloc[21:] *= 3  # the jump only shows up spanning the gap
    assert "return_outliers" in check_series("QQQ", s)
    assert check_series("QQQ", s)["return_outliers"]["flagged_count"] == 0


def test_run_validation_on_fixture_cache_writes_report(pulled, mini_config, tmp_path):
    out = tmp_path / "data_quality.json"
    report = run_validation(cache_dir=pulled["cache_dir"], out_path=out, config=mini_config)
    assert report["passed"] is True
    written = json.loads(out.read_text())
    assert set(written["series"]) == {"QQQ", "TQQQ", "^VIX", "FRED:DFF", "FRED:DGS3MO"}
    assert written["series"]["FRED:DGS3MO"]["alignment"]["forward_fill"] > 0
    assert written["series"]["QQQ"]["content_hash"]


def test_run_validation_fails_loudly_but_still_writes_report(tmp_path, mini_config):
    directory, out = tmp_path / "cache", tmp_path / "report.json"
    cache.write_series(directory, "TQQQ", _prices(p20=0.0), {"source": "test"})
    with pytest.raises(DataQualityError, match="non_positive_prices"):
        run_validation(cache_dir=directory, out_path=out, config=mini_config)
    written = json.loads(out.read_text())
    assert written["passed"] is False
    assert written["hard_error_count"] == 1


def test_run_validation_with_empty_cache_fails(tmp_path, mini_config):
    with pytest.raises(DataQualityError, match="no cached series"):
        run_validation(
            cache_dir=tmp_path / "none", out_path=tmp_path / "r.json", config=mini_config
        )
