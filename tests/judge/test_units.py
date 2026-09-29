"""Unit tests for each judge test, on hand-built inputs."""

import json

import numpy as np
import pandas as pd
import pytest
from cryptography.fernet import Fernet
from scipy import stats

from core.config import load_thresholds
from core.data.splits import encrypt_holdout
from core.judge.common import JudgeError, TestResult, column_sharpes, sharpe
from core.judge.dsr import EULER_GAMMA, dsr_test, expected_max_sharpe
from core.judge.holdout import holdout_passes, score_holdout
from core.judge.pbo import cscv_logits, pbo_test
from core.judge.permutation import permutation_test
from core.judge.regime import regime_test
from core.judge.sensitivity import neighbor_params, sensitivity_test
from core.judge.spa import spa_test
from core.judge.stress import stress_test
from core.judge.verdict import JUDGE_SEED, TEST_ORDER, thresholds_hash

TH = load_thresholds()


def dates(n: int) -> pd.DatetimeIndex:
    return pd.bdate_range("2012-01-02", periods=n)


def noise(n: int, cols: int = 1, seed: int = 0, mean: float = 0.0, sd: float = 0.01):
    rng = np.random.default_rng(seed)
    return pd.DataFrame(rng.normal(mean, sd, (n, cols)), index=dates(n))


# ---- common ---------------------------------------------------------------------------------


def test_sharpe_annualizes_and_flags_constant_series():
    x = noise(1000, seed=1)[0]
    assert sharpe(x) == pytest.approx(x.mean() / x.std(ddof=1) * np.sqrt(252))
    assert np.isnan(sharpe(pd.Series(0.001, index=dates(50))))
    assert np.isnan(column_sharpes(pd.DataFrame({"a": [0.1, 0.1, 0.1]}))[0])


def test_result_dict_is_json_safe_and_matches_spec_shape():
    res = TestResult("x", float("nan"), 0.5, False, {"a": np.float64(1.5), "b": (np.int64(2),)})
    out = res.to_dict()
    assert set(out) == {"value", "threshold", "pass", "details"}
    assert out["value"] is None and out["details"] == {"a": 1.5, "b": [2]}
    json.dumps(out, allow_nan=False)


# ---- test 1: DSR ----------------------------------------------------------------------------


def test_expected_max_sharpe_matches_the_formula():
    sharpes = np.array([0.02, -0.01, 0.03, 0.0, 0.01])
    n = 100
    want = np.sqrt(sharpes.var(ddof=1)) * (
        (1 - EULER_GAMMA) * stats.norm.ppf(1 - 1 / n)
        + EULER_GAMMA * stats.norm.ppf(1 - 1 / (n * np.e))
    )
    assert expected_max_sharpe(sharpes, n) == pytest.approx(want)
    assert expected_max_sharpe(sharpes, 1) == 0.0


def test_dsr_falls_as_trials_grow_and_rises_with_sharpe():
    x = noise(1500, seed=2, mean=0.0006)[0]
    trials = noise(1500, 30, seed=3)
    few = dsr_test(x, trials, 2, TH.dsr).value
    many = dsr_test(x, trials, 5000, TH.dsr).value
    assert many < few
    strong = dsr_test(x + 0.001, trials, 30, TH.dsr).value
    assert strong > dsr_test(x, trials, 30, TH.dsr).value


def test_dsr_passes_a_strong_single_trial_and_rejects_zero_edge():
    strong = noise(2500, seed=4, mean=0.0012)[0]
    assert dsr_test(strong, noise(2500, 1, seed=5), 1, TH.dsr).passed
    assert not dsr_test(noise(2500, seed=6)[0], noise(2500, 10, seed=7), 10, TH.dsr).passed


def test_dsr_is_not_evaluable_on_constant_returns():
    res = dsr_test(pd.Series(0.001, index=dates(100)), noise(100, 5), 5, TH.dsr)
    assert not res.passed and res.value is None


# ---- test 2: SPA ----------------------------------------------------------------------------


def test_spa_rejects_when_a_model_clearly_beats_the_benchmark():
    bench = noise(1500, seed=8)[0]
    models = noise(1500, 20, seed=9)
    models[0] = bench + 0.002 + noise(1500, seed=10)[0] * 0.2
    res = spa_test(bench, models, TH.spa, seed=1)
    assert res.passed and res.value <= 0.05


def test_spa_does_not_reject_when_all_models_are_noise():
    bench = noise(1500, seed=11)[0]
    res = spa_test(bench, noise(1500, 20, seed=12), TH.spa, seed=1)
    assert not res.passed


def test_spa_is_seed_deterministic_and_skips_identical_models():
    bench = noise(800, seed=13)[0]
    models = noise(800, 5, seed=14)
    models["same"] = bench
    a = spa_test(bench, models, TH.spa, seed=3)
    assert a.value == spa_test(bench, models, TH.spa, seed=3).value
    assert a.details["n_models"] == 5


def test_spa_with_only_benchmark_clones_is_not_evaluable():
    bench = noise(200, seed=15)[0]
    res = spa_test(bench, pd.DataFrame({"a": bench}), TH.spa, seed=1)
    assert not res.passed and res.value is None


# ---- test 3: PBO ----------------------------------------------------------------------------


def test_pbo_reports_insufficient_trials_and_does_not_pass():
    res = pbo_test(noise(800, TH.pbo.min_trials - 1), dates(800), TH.pbo)
    assert not res.passed and res.value is None
    assert res.details["status"] == "insufficient_trials"


def test_pbo_is_high_on_noise_and_low_when_one_trial_dominates_consistently():
    n = 800
    m = noise(n, 60, seed=16)
    assert pbo_test(m, dates(n), TH.pbo).value > 0.3
    # a persistent winner: trial 0 has a real edge in every block, the rest are noise
    m[0] = m[0] + 0.002
    res = pbo_test(m, dates(n), TH.pbo)
    assert res.value < 0.05 and res.passed


def test_cscv_uses_all_splits_and_drops_leading_remainder():
    m = noise(803, 10, seed=17).to_numpy()
    logits = cscv_logits(m, 16)
    assert len(logits) == 12870
    assert np.array_equal(logits, cscv_logits(m[3:], 16))
    with pytest.raises(ValueError):
        cscv_logits(m, 15)


def test_pbo_ignores_trials_that_do_not_cover_the_window():
    m = noise(800, 60, seed=18)
    m.iloc[:100, 5:] = np.nan
    res = pbo_test(m, dates(800), TH.pbo)
    assert res.details["n_comparable_trials"] == 5 and not res.passed


# ---- test 4: permutation --------------------------------------------------------------------


def _timed_world(n=1500, edge=True, seed=20):
    rng = np.random.default_rng(seed)
    state = np.zeros(n)
    for i in range(1, n):
        state[i] = 0.98 * state[i - 1] + rng.normal()
    held = pd.Series((state > 0).astype(float), index=dates(n))
    fund = pd.Series(rng.normal(0, 0.01, n), index=dates(n))
    if edge:
        fund = fund + held * 0.002
    return held, fund, pd.Series(0.0001, index=dates(n))


def test_permutation_detects_timing_and_not_its_absence():
    held, fund, rf = _timed_world(edge=True)
    assert permutation_test(held, fund, rf, 5, TH.permutation, seed=1).passed
    held, fund, rf = _timed_world(edge=False)
    assert not permutation_test(held, fund, rf, 5, TH.permutation, seed=1).passed


def test_permutation_shift_count_rules():
    held, fund, rf = _timed_world(n=1500)
    short = permutation_test(held, fund, rf, 5, TH.permutation, seed=1)
    assert short.details["full_enumeration"] and short.details["n_shifts"] == 1499
    held, fund, rf = _timed_world(n=5400)
    long = permutation_test(held, fund, rf, 5, TH.permutation, seed=1)
    assert not long.details["full_enumeration"] and long.details["n_shifts"] == 5000
    again = permutation_test(held, fund, rf, 5, TH.permutation, seed=1)
    assert again.value == long.value


def test_permutation_null_matches_a_direct_rotation():
    from core.engine.backtest import simulate

    held, fund, rf = _timed_world(n=300)
    res = permutation_test(held, fund, rf, 5, TH.permutation, seed=1)
    rotated = pd.Series(np.roll(held.to_numpy(), 7), index=held.index)
    ret = simulate(rotated, fund, rf, 5)["return"]
    from core.judge.permutation import _shifted_sharpes

    got = _shifted_sharpes(held.to_numpy(), (fund - rf).to_numpy(), 5 / 1e4, np.array([7]))[0]
    assert got == pytest.approx(sharpe(ret - rf))
    assert res.details["n_shifts"] == 299


def test_permutation_rejects_misaligned_inputs():
    held, fund, rf = _timed_world(n=100)
    with pytest.raises(JudgeError):
        permutation_test(held, fund.iloc[1:], rf, 5, TH.permutation, seed=1)


# ---- test 5: sensitivity --------------------------------------------------------------------


def test_neighbor_params_perturb_one_numeric_parameter_at_a_time():
    out = neighbor_params({"w": 20, "x": 0.5, "flag": True, "mode": "a", "z": 0}, [0.2, 0.4])
    assert {p["w"] for p in out if p["w"] != 20} == {12, 16, 24, 28}
    assert sorted(p["x"] for p in out if p["x"] != 0.5) == pytest.approx([0.3, 0.4, 0.6, 0.7])
    assert all(p["flag"] is True and p["mode"] == "a" and p["z"] == 0 for p in out)
    assert len(out) == 8
    assert all(sum(p[k] != v for k, v in {"w": 20, "x": 0.5}.items()) == 1 for p in out)


def test_neighbor_params_drop_neighbors_that_round_back():
    assert neighbor_params({"w": 2}, [0.2]) == []


def _sens(neighbor_mean: float, base_mean: float = 0.001, bench_mean: float = 0.0002):
    n = 1000
    base = noise(n, seed=30, mean=base_mean)[0]
    bench = noise(n, seed=31, mean=bench_mean)[0]
    rf = pd.Series(0.0, index=dates(n))

    def evaluate(params):
        return noise(n, seed=32 + params["w"], mean=neighbor_mean)[0]

    return sensitivity_test(base, bench, {"w": 20}, evaluate, rf, TH.sensitivity)


def test_sensitivity_passes_a_plateau_and_fails_a_spike():
    assert _sens(0.001).passed
    spike = _sens(0.0)
    assert not spike.passed and spike.value < 0.6


def test_sensitivity_fails_closed():
    n = 500
    base = noise(n, seed=33, mean=0.001)[0]
    rf = pd.Series(0.0, index=dates(n))
    args = (base, base, {"w": 20}, lambda p: base, rf, TH.sensitivity)
    assert not sensitivity_test(*args[:3], None, *args[4:]).passed
    assert not sensitivity_test(base, base, {"name": "x"}, args[3], rf, TH.sensitivity).passed
    losing = -base.abs() * 0.01
    assert not sensitivity_test(
        losing, base, {"w": 20}, lambda p: losing, rf, TH.sensitivity
    ).passed


# ---- test 6: stress -------------------------------------------------------------------------


def test_stress_uses_the_configured_multipliers_and_strict_inequality():
    n = 800
    rf = pd.Series(0.0, index=dates(n))
    bench = noise(n, seed=40)[0]
    seen = []

    def fn(cost_mult, spread_bps):
        seen.append((cost_mult, spread_bps))
        return bench + 0.001, bench

    res = stress_test(fn, rf, TH.stress)
    assert seen == [(3.0, 200)] and res.passed and res.value > 0
    assert not stress_test(lambda c, s: (bench, bench), rf, TH.stress).passed  # exactly 0
    assert not stress_test(None, rf, TH.stress).passed


# ---- test 7: regimes ------------------------------------------------------------------------


def _regime_frame(n=1500, seed=50):
    idx = dates(n)
    rng = np.random.default_rng(seed)
    vix = pd.Series(rng.uniform(10, 40, n), index=idx)
    return idx, vix


def test_regime_passes_a_steady_edge_and_fails_a_single_year_edge():
    idx, vix = _regime_frame()
    bench = pd.Series(0.0, index=idx)
    steady = pd.Series(0.001, index=idx) + noise(len(idx), seed=51)[0] * 0.001
    assert regime_test(steady, bench, vix, TH.regime).passed
    one_year = pd.Series(-0.0001, index=idx)
    one_year[idx.year == idx.year[300]] = 0.01
    res = regime_test(one_year, bench, vix, TH.regime)
    assert not res.passed


def test_regime_share_rule_and_missing_vix():
    idx, vix = _regime_frame()
    bench = pd.Series(0.0, index=idx)
    steady = pd.Series(0.001, index=idx)
    # high-VIX days carry ~all the edge, so one tercile has more than half of the excess
    lopsided = steady.where(vix > vix.quantile(2 / 3), 0.00001)
    res = regime_test(lopsided, bench, vix, TH.regime)
    assert not res.passed and res.details["max_single_regime_share"] > 0.5
    assert not regime_test(steady, bench, None, TH.regime).passed


# ---- test 8: hold-out -----------------------------------------------------------------------


def test_holdout_pass_rules():
    idx = dates(400)
    rf = pd.Series(0.0, index=idx)
    bench = noise(400, seed=60)[0]
    ok, _ = holdout_passes(bench + 0.001, bench, rf, 0.05, TH.holdout)
    assert ok
    worse, _ = holdout_passes(bench - 0.001, bench, rf, 0.05, TH.holdout)
    assert not worse  # sign flipped
    flat, _ = holdout_passes(bench, bench, rf, 0.05, TH.holdout)
    assert not flat  # no excess return


def test_score_holdout_returns_only_verdict_and_timestamp(tmp_path):
    key = Fernet.generate_key()  # disposable, never the real hold-out key
    idx = dates(300)
    frame = pd.DataFrame({"X": noise(300, seed=61)[0].to_numpy()}, index=idx)
    path = tmp_path / "holdout.enc"
    encrypt_holdout(frame, key, path)

    def run(df):
        bench = df["X"]
        return bench + 0.001, bench, pd.Series(0.0, index=df.index)

    out = score_holdout(
        "H-0001", run, 0.1, TH.holdout, key=key, holdout_path=path, results_dir=tmp_path
    )
    assert set(out) == {"hypothesis_id", "holdout_verdict", "scored_at"}
    assert out["holdout_verdict"] == "pass"
    saved = json.loads((tmp_path / "holdout" / "H-0001.json").read_text())
    assert saved["passed"] is True and "excess_sharpe" in saved
    with pytest.raises(Exception):  # noqa: B017 - Fernet raises InvalidToken for a wrong key
        score_holdout(
            "H-0002",
            run,
            0.1,
            TH.holdout,
            key=Fernet.generate_key(),
            holdout_path=path,
            results_dir=tmp_path,
        )


# ---- verdict --------------------------------------------------------------------------------


def test_thresholds_hash_is_the_file_sha256():
    import hashlib

    from core.config import CONFIG_DIR

    assert (
        thresholds_hash()
        == hashlib.sha256((CONFIG_DIR / "thresholds.yaml").read_bytes()).hexdigest()
    )
    assert TEST_ORDER == ("dsr", "spa", "pbo", "permutation", "sensitivity", "stress", "regime")
    assert isinstance(JUDGE_SEED, int)
