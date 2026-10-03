"""``lab dose-response``: check a hypothesis's mechanism across leverage variants (SPEC Section 15).

This is the leverage-aware caller of the generic ``core.judge.dose_response`` test, which never
sees a leverage or a ticker. For a hypothesis built on the vol-drag mechanism, the effect of its
chosen signal (excess return, or excess Sharpe, over buy-and-hold of the same fund) should scale
roughly with ``L ** 2`` and reverse for inverse funds. This module:

1. takes the chosen trial of the hypothesis (as ``lab judge`` does),
2. rebuilds the fund at each leverage factor with the Section 4.2 synthetic builder from the
   spec's underlying (always ``synthetic_long``: real funds exist at only a few factors),
3. re-runs the chosen signal on each variant through the engine and records the effect, and
4. hands the leverage factors (as ``dose``) and the effects to the generic test.

The re-runs are diagnostics of the one chosen point, like the judge's neighbor and stress
re-evaluations: they select nothing and are not ledger trials. The check can only withhold
support from a mechanism claim, never produce an ``advance``. It is deliberately invoked and
is not part of ``lab judge``'s battery.
"""

from __future__ import annotations

import json

from core.config import load_thresholds
from core.data import cache
from core.data.synthetic import LEVERAGE_FACTORS, underlying_for
from core.engine.backtest import run_backtest
from core.judge.dose_response import NOT_EVALUABLE, SUPPORTED, dose_response_test
from core.judge_runner import Context, prepare
from core.runner import RunError, build_inputs

METRICS = ("excess_return", "excess_sharpe")
FLAG_NOT_SUPPORTED = "mechanism not supported"


def _effect(result, metric: str) -> float:
    strategy, benchmark = result.metrics, result.benchmarks["buy_and_hold"].metrics
    key = "cagr" if metric == "excess_return" else "sharpe"
    return float(strategy[key] - benchmark[key])


def leverage_effects(
    ctx: Context, metric: str = "excess_return", factors=LEVERAGE_FACTORS
) -> tuple[dict[float, float], dict]:
    """The chosen signal's effect on the synthetic fund at each leverage factor, and the window."""
    if metric not in METRICS:
        raise RunError(f"unknown metric {metric!r}; choose from {', '.join(METRICS)}")
    uni = ctx.spec.universe
    underlying = uni.underlying or underlying_for(uni.fund)
    effects, window = {}, None
    for factor in factors:
        variant = ctx.spec.model_copy(
            update={
                "universe": uni.model_copy(
                    update={
                        "research_universe": "synthetic_long",
                        "leverage": factor,
                        "underlying": underlying,
                    }
                )
            }
        )
        features, returns, rf, _ = build_inputs(variant)
        result = run_backtest(
            ctx.factory(**ctx.chosen["params"]), features, returns, rf, ctx.config
        )
        effects[float(factor)] = _effect(result, metric)
        window = [str(returns.index[0].date()), str(returns.index[-1].date())]
    return effects, {"window": window, "underlying": underlying}


def dose_response_hypothesis(
    hypothesis_id: str, metric: str = "excess_return", ctx: Context | None = None
) -> dict:
    """Run the check on the chosen trial; write ``results/<id>/dose_response.json``."""
    ctx = ctx or prepare(hypothesis_id)
    criteria = load_thresholds().dose_response
    effects, meta = leverage_effects(ctx, metric)
    doses = sorted(effects)
    result = dose_response_test(doses, [effects[d] for d in doses], criteria)
    spec_leverage = float(ctx.spec.universe.leverage)
    at_spec = effects.get(spec_leverage)
    works = at_spec is not None and at_spec > 0
    if result.status == SUPPORTED:
        flag = "supported"
    elif result.status == NOT_EVALUABLE:
        flag = "not evaluable"
    elif works:
        flag = FLAG_NOT_SUPPORTED
    else:
        flag = "not applicable: no positive effect at the spec's own leverage"
    payload = {
        "hypothesis_id": hypothesis_id,
        "chosen_trial": ctx.chosen["trial_id"],
        "chosen_params": ctx.chosen["params"],
        "metric": metric,
        "spec_leverage": spec_leverage,
        "effect_at_spec_leverage": at_spec,
        "works_at_spec_leverage": works,
        "flag": flag,
        "effects": {f"{d:g}": effects[d] for d in doses},
        "criteria": criteria.model_dump(),
        "dose_response": result.to_dict(),
        **meta,
        "note": "diagnostic re-runs of the chosen point on synthetic variants; not ledger trials",
    }
    out = cache.results_dir() / hypothesis_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "dose_response.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return payload
