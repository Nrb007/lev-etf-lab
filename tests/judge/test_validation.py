"""The four judge validation tests required by SPEC Section 6.4.

All worlds are simulated (see ``harness.py``); no real hypothesis is registered. Each test runs
the full seven-test battery on the best in-sample trial of a family of signals, exactly as
``lab judge`` does. Set ``LAB_JUDGE_VALIDATION_OUT`` to a path to also write the measured rates
and the power table as JSON (for the dashboard's judge-validation page).
"""

import json
import os
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests.judge.harness import (
    grid_params,
    judge_world,
    make_world,
    population_sharpe,
    random_params,
)

NOMINAL_FALSE_POSITIVE = 0.05
# Monte Carlo tolerance: three binomial standard errors above the nominal rate for n runs.
N_NOISE = 200
TOLERANCE = 3 * np.sqrt(NOMINAL_FALSE_POSITIVE * (1 - NOMINAL_FALSE_POSITIVE) / N_NOISE)
NOISE_T = 1500

POWER_RUNS = 30
POWER_TARGET = 0.7  # at the strong edge and the long sample; see docs/decisions.md
POWER_GRID = {"betas": (0.2, 0.3), "ts": (1500, 3000)}

N_SNOOP_VARIANTS = 500
N_SNOOP_WORLDS = 8

REPORT: dict = {}


@pytest.fixture(scope="module", autouse=True)
def write_report():
    yield
    out = os.environ.get("LAB_JUDGE_VALIDATION_OUT")
    if out and REPORT:
        Path(out).write_text(json.dumps(REPORT, indent=2, sort_keys=True) + "\n")


def _advance_rate(verdicts: list[dict]) -> float:
    return sum(v["train_verdict"] == "advance" for v in verdicts) / len(verdicts)


def test_noise_is_advanced_at_or_below_the_nominal_false_positive_rate():
    """200 strategy families on pure Gaussian noise: the advance rate stays within tolerance."""
    verdicts = [
        judge_world(make_world(seed, NOISE_T), grid_params(), seed=seed) for seed in range(N_NOISE)
    ]
    rate = _advance_rate(verdicts)
    failing = Counter(r for v in verdicts for r in v["reasons"])
    REPORT["noise"] = {
        "n": N_NOISE,
        "t": NOISE_T,
        "advance_rate": rate,
        "nominal": NOMINAL_FALSE_POSITIVE,
        "tolerance": TOLERANCE,
        "rejections_by_test": dict(failing),
    }
    assert rate <= NOMINAL_FALSE_POSITIVE + TOLERANCE, (rate, dict(failing))


def test_planted_edge_is_advanced_above_the_target_power():
    """Power as a function of edge size (population Sharpe) and T; assert the strong cell."""
    table = []
    for beta in POWER_GRID["betas"]:
        for t in POWER_GRID["ts"]:
            verdicts = [
                judge_world(make_world(1000 + s, t, beta), grid_params(), seed=s)
                for s in range(POWER_RUNS)
            ]
            table.append(
                {
                    "edge_sharpe": round(population_sharpe(beta), 2),
                    "beta": beta,
                    "t": t,
                    "power": _advance_rate(verdicts),
                    "runs": POWER_RUNS,
                    "rejections_by_test": dict(Counter(r for v in verdicts for r in v["reasons"])),
                }
            )
    REPORT["planted_edge"] = table
    frame = pd.DataFrame(table).pivot(index="edge_sharpe", columns="t", values="power")
    print("\npower by edge Sharpe (rows) and T (columns):\n", frame.to_string())
    strong = max(POWER_GRID["betas"]), max(POWER_GRID["ts"])
    cell = next(r for r in table if (r["beta"], r["t"]) == strong)
    assert cell["power"] >= POWER_TARGET, cell
    # more data and a bigger edge should not lower power (allowing Monte Carlo slack)
    by = {(r["beta"], r["t"]): r["power"] for r in table}
    slack = 2 * np.sqrt(0.25 / POWER_RUNS)
    for beta in POWER_GRID["betas"]:
        assert by[(beta, 3000)] >= by[(beta, 1500)] - slack
    for t in POWER_GRID["ts"]:
        assert by[(0.3, t)] >= by[(0.2, t)] - slack


def test_snooping_500_random_variants_of_a_null_signal_is_rejected():
    """The best of 500 random-parameter variants looks good in-sample and must still be rejected."""
    verdicts, best_sharpes = [], []
    for seed in range(N_SNOOP_WORLDS):
        world = make_world(5000 + seed, NOISE_T)
        variants = random_params(np.random.default_rng(seed), N_SNOOP_VARIANTS)
        verdict = judge_world(world, variants, seed=seed)
        verdicts.append(verdict)
        best_sharpes.append(verdict["tests"]["dsr"]["details"]["sharpe_per_period"] * np.sqrt(252))
    REPORT["snooping"] = {
        "variants": N_SNOOP_VARIANTS,
        "worlds": N_SNOOP_WORLDS,
        "advance_rate": _advance_rate(verdicts),
        "median_best_in_sample_sharpe": float(np.median(best_sharpes)),
    }
    # the test has teeth: picking the best of 500 does produce an impressive in-sample Sharpe
    assert np.median(best_sharpes) > 0.8, best_sharpes
    assert all(v["train_verdict"] == "reject" for v in verdicts)
    assert all(v["n_trials"] == N_SNOOP_VARIANTS for v in verdicts)


def test_same_inputs_and_seed_give_identical_verdicts():
    world = make_world(7, 1500, beta=0.25)
    first = judge_world(world, grid_params(), seed=11)
    second = judge_world(make_world(7, 1500, beta=0.25), grid_params(), seed=11)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    # the seed is recorded, and it drives the resampling tests
    other = judge_world(world, grid_params(), seed=12)
    assert other["seed"] == 12 and first["seed"] == 11
    assert other["tests"]["spa"]["value"] != first["tests"]["spa"]["value"]
