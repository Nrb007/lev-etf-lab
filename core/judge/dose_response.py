"""Optional dose-response check (SPEC Section 15).

Given a ``dose`` array (any numeric scale) and the ``effect`` measured at each dose, test whether
the effect grows roughly with ``|dose| ** 2`` and flips sign for negative doses, i.e. whether it
follows ``effect = k * sign(dose) * |dose| ** 2`` for some ``k``. Three sub-tests, each reported
like the judge's other tests:

* ``scaling``: the slope of ``log|effect|`` on ``log|dose|`` is within a tolerance of 2. This is
  what separates a quadratic response from a linear one.
* ``sign_reversal``: the share of points whose effect has the sign the model predicts (the sign of
  the positive-dose effects, flipped for negative doses) is at least the threshold.
* ``fit``: R-squared of the through-the-origin fit of the model above is at least the threshold.

The check is generic: it never sees what a dose or an effect is, so the caller decides that and
supplies the arrays. It is *not* one of the eight required tests and ``lab judge`` does not run it.
A check that cannot be evaluated (too few points, no doses of one sign, no variation) never
counts as supported.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from core.config import DoseResponse
from core.judge.common import STD_FLOOR, JudgeError, TestResult, _plain, not_evaluable

SUPPORTED = "supported"
NOT_SUPPORTED = "not_supported"
NOT_EVALUABLE = "not_evaluable"


@dataclass(frozen=True)
class DoseResponseResult:
    status: str  # supported | not_supported | not_evaluable
    tests: dict[str, TestResult]
    details: dict = field(default_factory=dict)

    @property
    def supported(self) -> bool:
        return self.status == SUPPORTED

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "supported": self.supported,
            "tests": {name: t.to_dict() for name, t in self.tests.items()},
            "details": _plain(self.details),
        }


def _signed_power(dose: np.ndarray, exponent: float) -> np.ndarray:
    return np.sign(dose) * np.abs(dose) ** exponent


def _scaling(dose: np.ndarray, effect: np.ndarray, c: DoseResponse) -> TestResult:
    keep = np.abs(effect) > STD_FLOOR
    if keep.sum() < 3 or len(np.unique(np.abs(dose[keep]))) < 2:
        return not_evaluable(
            "scaling", "need 3 non-zero effects at 2 or more distinct dose magnitudes"
        )
    x, y = np.log(np.abs(dose[keep])), np.log(np.abs(effect[keep]))
    x_centered = x - x.mean()
    slope = float(x_centered @ (y - y.mean()) / (x_centered @ x_centered))
    residual = y - y.mean() - slope * x_centered
    dof = int(keep.sum()) - 2
    se = float(np.sqrt(residual @ residual / dof / (x_centered @ x_centered))) if dof else None
    return TestResult(
        "scaling",
        slope,
        c.expected_exponent,
        abs(slope - c.expected_exponent) <= c.exponent_tolerance,
        {"tolerance": c.exponent_tolerance, "slope_se": se, "points_used": int(keep.sum())},
    )


def _sign_reversal(dose: np.ndarray, effect: np.ndarray, c: DoseResponse) -> TestResult:
    positive_sum = float(effect[dose > 0].sum())
    if not (dose > 0).any() or not (dose < 0).any():
        return not_evaluable("sign_reversal", "need doses of both signs", c.min_sign_agreement)
    if abs(positive_sum) <= STD_FLOOR:
        return not_evaluable(
            "sign_reversal", "positive-dose effects sum to zero", c.min_sign_agreement
        )
    expected = np.sign(positive_sum) * np.sign(dose)
    agree = np.sign(effect) == expected
    return TestResult(
        "sign_reversal",
        float(agree.mean()),
        c.min_sign_agreement,
        bool(agree.mean() >= c.min_sign_agreement),
        {
            "positive_dose_sign": int(np.sign(positive_sum)),
            "points_agreeing": int(agree.sum()),
            "points": len(dose),
        },
    )


def _fit(dose: np.ndarray, effect: np.ndarray, c: DoseResponse) -> TestResult:
    x = _signed_power(dose, c.expected_exponent)
    total = float(((effect - effect.mean()) ** 2).sum())
    if total <= STD_FLOOR**2:
        return not_evaluable("fit", "effects do not vary", c.min_r2)
    k = float(x @ effect / (x @ x))
    r2 = 1 - float(((effect - k * x) ** 2).sum()) / total
    return TestResult("fit", r2, c.min_r2, bool(r2 >= c.min_r2), {"k": k})


def dose_response_test(
    dose: np.ndarray | list[float],
    effect: np.ndarray | list[float],
    criteria: DoseResponse | None = None,
) -> DoseResponseResult:
    """Test ``effect ~ k * sign(dose) * |dose| ** p`` (``p`` = ``criteria.expected_exponent``).

    Zero doses are ignored (a model through the origin says nothing about them). Raises
    ``JudgeError`` on mismatched lengths or non-finite values.
    """
    criteria = criteria or DoseResponse()
    d, e = np.asarray(dose, dtype="float64"), np.asarray(effect, dtype="float64")
    if d.ndim != 1 or d.shape != e.shape:
        raise JudgeError("dose and effect must be 1-D arrays of the same length")
    if not (np.isfinite(d).all() and np.isfinite(e).all()):
        raise JudgeError("dose and effect must be finite")
    nonzero = d != 0
    d, e = d[nonzero], e[nonzero]
    details = {"points": int(len(d)), "doses": sorted(set(d.tolist()))}
    if len(d) < criteria.min_points:
        reason = f"need at least {criteria.min_points} non-zero doses, got {len(d)}"
        tests = {name: not_evaluable(name, reason) for name in ("scaling", "sign_reversal", "fit")}
        return DoseResponseResult(NOT_EVALUABLE, tests, details)
    tests = {
        "scaling": _scaling(d, e, criteria),
        "sign_reversal": _sign_reversal(d, e, criteria),
        "fit": _fit(d, e, criteria),
    }
    if any(t.value is None for t in tests.values()):
        status = NOT_EVALUABLE
    else:
        status = SUPPORTED if all(t.passed for t in tests.values()) else NOT_SUPPORTED
    return DoseResponseResult(status, tests, details)
