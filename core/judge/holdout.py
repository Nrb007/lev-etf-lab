"""Test 8: hold-out scoring logic (SPEC Section 6.3).

The only module that decrypts the hold-out slice. ``score_holdout`` decrypts it in-process, hands
it to a caller-supplied ``run`` that executes the frozen signal, judges the result and returns
**only** pass/fail and a timestamp. Nothing about the hold-out numbers is printed, logged or
returned; the full metrics go to ``results/holdout/<id>.json`` (deny-listed for agents, read by
the human-run dashboard build).

The one-shot rule, the pre-registered (frozen) signal and the ``advance`` precondition are enforced
by the caller (``core/judge_runner.py``); ``on_decrypted`` is the seam where it consumes the
hypothesis's single attempt: after the slice is decrypted, before the signal ever sees it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from core.config import Holdout
from core.data import cache
from core.data.splits import decrypt_holdout
from core.engine.metrics import cagr
from core.judge.common import excess_sharpe

# frame -> (strategy raw returns, benchmark raw returns, daily risk-free), one shared index
RunFn = Callable[[pd.DataFrame], tuple[pd.Series, pd.Series, pd.Series]]


def holdout_passes(
    strategy: pd.Series,
    benchmark: pd.Series,
    rf_daily: pd.Series,
    train_excess_return: float,
    thresholds: Holdout,
) -> tuple[bool, dict]:
    """Same sign of excess return as train, above the floor, and excess Sharpe at the floor."""
    excess_return = cagr(strategy) - cagr(benchmark)
    ex_sharpe = excess_sharpe(strategy - rf_daily, benchmark - rf_daily)
    same_sign = bool(np.sign(excess_return) == np.sign(train_excess_return) != 0)
    passed = bool(
        same_sign
        and excess_return >= thresholds.min_excess_return
        and np.isfinite(ex_sharpe)
        and ex_sharpe >= thresholds.min_excess_sharpe
    )
    metrics = {
        "excess_return_cagr": float(excess_return),
        "excess_sharpe": float(ex_sharpe),
        "train_excess_return_cagr": float(train_excess_return),
        "same_sign_as_train": same_sign,
        "n_obs": len(strategy),
        "start": str(strategy.index[0].date()),
        "end": str(strategy.index[-1].date()),
    }
    return passed, metrics


def score_holdout(
    hypothesis_id: str,
    run: RunFn,
    train_excess_return: float,
    thresholds: Holdout,
    *,
    key: bytes | str,
    holdout_path: Path | None = None,
    results_dir: Path | None = None,
    on_decrypted: Callable[[], None] | None = None,
) -> dict:
    """Decrypt, run, judge. Returns ``{"hypothesis_id", "holdout_verdict", "scored_at"}`` only.

    A missing file or wrong key raises before ``on_decrypted`` is called, so it costs no attempt.
    """
    frame = decrypt_holdout(holdout_path or cache.holdout_path(), key)
    if on_decrypted is not None:
        on_decrypted()
    strategy, benchmark, rf = run(frame)
    passed, metrics = holdout_passes(strategy, benchmark, rf, train_excess_return, thresholds)
    scored_at = datetime.now(UTC).isoformat(timespec="seconds")
    out_dir = (results_dir or cache.results_dir()) / "holdout"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{hypothesis_id}.json").write_text(
        json.dumps(
            {"hypothesis_id": hypothesis_id, "passed": passed, "scored_at": scored_at, **metrics},
            indent=2,
            sort_keys=True,
        )
    )
    return {
        "hypothesis_id": hypothesis_id,
        "holdout_verdict": "pass" if passed else "fail",
        "scored_at": scored_at,
    }
