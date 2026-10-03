"""The dose-response check on arrays with a constructed relationship.

Nothing here refers to what a dose or an effect is: the module under test is generic, and the
last test proves its source does not mention the things it must not know about.
"""

import re
from pathlib import Path

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.config import DoseResponse
from core.judge import dose_response as module
from core.judge.common import JudgeError
from core.judge.dose_response import (
    NOT_EVALUABLE,
    NOT_SUPPORTED,
    SUPPORTED,
    dose_response_test,
)

DOSES = np.array([-3.0, -2.0, -1.0, 1.0, 2.0, 3.0])


def odd_square(dose, k=0.02):
    return k * np.sign(dose) * np.abs(dose) ** 2


def test_exact_odd_quadratic_is_supported():
    result = dose_response_test(DOSES, odd_square(DOSES))
    assert result.status == SUPPORTED and result.supported
    assert result.tests["scaling"].value == pytest.approx(2.0)
    assert result.tests["sign_reversal"].value == 1.0
    assert result.tests["fit"].value == pytest.approx(1.0)
    assert result.tests["fit"].details["k"] == pytest.approx(0.02)


def test_negative_constant_is_supported_with_a_negative_fit_constant():
    result = dose_response_test(DOSES, odd_square(DOSES, k=-0.5))
    assert result.supported and result.tests["fit"].details["k"] == pytest.approx(-0.5)


def test_linear_response_fails_scaling_even_though_sign_and_fit_look_fine():
    result = dose_response_test(DOSES, 0.05 * DOSES)
    assert result.status == NOT_SUPPORTED
    assert not result.tests["scaling"].passed and result.tests["scaling"].value == pytest.approx(1)
    assert result.tests["sign_reversal"].passed  # a linear response is odd too


def test_even_response_fails_sign_reversal_and_fit():
    result = dose_response_test(DOSES, 0.02 * DOSES**2)
    assert result.status == NOT_SUPPORTED
    assert result.tests["scaling"].passed  # the magnitudes do scale with dose squared
    assert not result.tests["sign_reversal"].passed and not result.tests["fit"].passed


def test_cubic_response_fails_scaling():
    result = dose_response_test(DOSES, 0.01 * DOSES**3)
    assert result.status == NOT_SUPPORTED and not result.tests["scaling"].passed


def test_expected_exponent_is_a_parameter_of_the_criteria():
    cubic = 0.01 * DOSES**3
    assert dose_response_test(DOSES, cubic, DoseResponse(expected_exponent=3.0)).supported


def test_pure_noise_is_not_supported():
    rng = np.random.default_rng(7)
    verdicts = [dose_response_test(DOSES, rng.normal(size=len(DOSES))).status for _ in range(200)]
    assert verdicts.count(SUPPORTED) / len(verdicts) <= 0.05


@settings(max_examples=60, deadline=None)
@given(
    k=st.floats(0.01, 5.0),
    sign=st.sampled_from([-1.0, 1.0]),
    seed=st.integers(0, 10_000),
    doses=st.lists(st.integers(1, 6), min_size=2, max_size=5, unique=True),
)
def test_property_small_noise_around_the_model_stays_supported(k, sign, seed, doses):
    dose = np.array([*doses, *(-d for d in doses)], dtype=float)
    noise = np.random.default_rng(seed).normal(0, 0.01 * k, len(dose))
    assert dose_response_test(dose, sign * odd_square(dose, k) + noise).supported


@settings(max_examples=60, deadline=None)
@given(k=st.floats(0.01, 5.0), scale=st.floats(0.001, 1000.0))
def test_property_rescaling_the_effect_or_the_dose_never_changes_the_status(k, scale):
    base = dose_response_test(DOSES, odd_square(DOSES, k)).status
    assert dose_response_test(DOSES, scale * odd_square(DOSES, k)).status == base
    assert dose_response_test(scale * DOSES, odd_square(DOSES, k)).status == base


def test_sign_reversal_tolerates_one_wrong_point_out_of_six_by_default_only():
    effect = odd_square(DOSES).copy()
    effect[2] = +0.001  # the smallest negative dose points the wrong way
    result = dose_response_test(DOSES, effect)
    assert result.tests["sign_reversal"].value == pytest.approx(5 / 6)
    assert result.tests["sign_reversal"].passed
    strict = dose_response_test(DOSES, effect, DoseResponse(min_sign_agreement=1.0))
    assert not strict.tests["sign_reversal"].passed and strict.status == NOT_SUPPORTED


def test_all_effects_flipped_together_is_still_a_valid_reversal_of_the_reference_sign():
    # The reference sign is the sign of the positive-dose effects, so a uniformly negative
    # response is as good as a uniformly positive one.
    assert dose_response_test(DOSES, -odd_square(DOSES)).supported


@pytest.mark.parametrize(
    "dose, effect",
    [
        ([1.0, 2.0, 3.0], [0.1, 0.4, 0.9]),  # too few points
        ([1.0, 2.0, 3.0, 4.0], [0.1, 0.4, 0.9, 1.6]),  # no negative doses
        ([-1.0, -2.0, -3.0, -4.0], [-0.1, -0.4, -0.9, -1.6]),  # no positive doses
        ([-2.0, -1.0, 1.0, 2.0], [0.0, 0.0, 0.0, 0.0]),  # nothing varies
        ([-1.0, 1.0, -1.0, 1.0], [-0.1, 0.1, -0.1, 0.1]),  # a single dose magnitude
    ],
)
def test_unevaluable_inputs_are_never_supported(dose, effect):
    result = dose_response_test(dose, effect)
    assert result.status == NOT_EVALUABLE and not result.supported


def test_zero_doses_are_ignored():
    dose = np.concatenate([[0.0], DOSES])
    assert dose_response_test(dose, np.concatenate([[5.0], odd_square(DOSES)])).supported


@pytest.mark.parametrize(
    "dose, effect",
    [
        ([1.0, 2.0], [1.0]),
        ([1.0, np.nan, 3.0, 4.0], [1.0, 2.0, 3.0, 4.0]),
        ([1.0, 2.0, 3.0, 4.0], [1.0, np.inf, 3.0, 4.0]),
        ([[1.0, 2.0], [3.0, 4.0]], [[1.0, 2.0], [3.0, 4.0]]),
    ],
)
def test_malformed_inputs_raise(dose, effect):
    with pytest.raises(JudgeError):
        dose_response_test(dose, effect)


def test_result_is_json_ready_and_deterministic():
    first = dose_response_test(DOSES, odd_square(DOSES)).to_dict()
    assert first == dose_response_test(DOSES, odd_square(DOSES)).to_dict()
    assert set(first["tests"]) == {"scaling", "sign_reversal", "fit"}
    assert first["status"] == SUPPORTED and first["supported"] is True


def test_module_is_asset_agnostic():
    source = Path(module.__file__).read_text().lower()
    for word in ("leverage", "ticker", "fund", "etf", "qqq", "soxx", "smh", "tqqq", "vix"):
        assert not re.search(rf"\b{word}", source), f"{word!r} must not appear in {module.__name__}"
