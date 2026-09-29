"""Data quality checks (SPEC Section 4.4).

Checks every cached series for missing sessions, non-positive prices, suspected splits, return
outliers and stale prices, and writes a machine-readable report. Hard errors are raised loudly
(after the report is written).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from core.config import LabConfig
from core.data import cache
from core.data.splits import load_prices

OUTLIER_FLAG = 0.40  # |daily return| beyond this is flagged
OUTLIER_HARD = 0.80  # ... and beyond this is a hard error
STALE_FLAG_RUN = 5  # identical consecutive prices
STALE_HARD_RUN = 20
MISSING_HARD_FRACTION = 0.01  # share of NYSE sessions with no value
SPLIT_RATIOS = (2, 3, 4, 5, 6, 8, 10, 15, 20, 25, 50)
SPLIT_TOLERANCE = 0.015
LIST_CAP = 100  # entries listed per check; counts are always complete


class DataQualityError(RuntimeError):
    """The cached data has hard errors."""


def _issue(severity: str, check: str, detail: str) -> dict:
    return {"severity": severity, "check": check, "detail": detail}


def _dates(index: pd.Index) -> list[str]:
    return [str(d.date()) for d in index[:LIST_CAP]]


def _stale_runs(values: pd.Series, min_run: int) -> list[dict]:
    same = values.eq(values.shift())
    group = (~same).cumsum()
    runs = []
    for _, chunk in values.groupby(group):
        if len(chunk) >= min_run:
            runs.append(
                {
                    "start": str(chunk.index[0].date()),
                    "end": str(chunk.index[-1].date()),
                    "length": int(len(chunk)),
                }
            )
    return runs


def _split_like(ratio: float) -> int | None:
    for k in SPLIT_RATIOS:
        if abs(ratio - k) / k < SPLIT_TOLERANCE or abs(ratio - 1 / k) * k < SPLIT_TOLERANCE:
            return k
    return None


def check_series(name: str, series: pd.Series) -> dict:
    """Quality report for one series over its own first..last valid date."""
    series = series.loc[series.first_valid_index() : series.last_valid_index()]
    issues: list[dict] = []
    report: dict = {
        "kind": "rate" if cache.is_rate(name) else "price",
        "rows": int(len(series)),
        "first_date": str(series.index[0].date()),
        "last_date": str(series.index[-1].date()),
    }

    missing = series.index[series.isna()]
    report["missing_days"] = {"count": int(len(missing)), "dates": _dates(missing)}
    if len(missing):
        fraction = len(missing) / len(series)
        severity = "error" if fraction > MISSING_HARD_FRACTION else "warning"
        issues.append(
            _issue(severity, "missing_days", f"{len(missing)} NYSE sessions have no value")
        )

    valid = series.dropna()
    if cache.is_rate(name):
        report["issues"] = issues
        return report

    bad = valid.index[valid <= 0]
    report["non_positive_prices"] = {"count": int(len(bad)), "dates": _dates(bad)}
    if len(bad):
        issues.append(_issue("error", "non_positive_prices", f"{len(bad)} prices <= 0"))
        valid = valid[valid > 0]

    returns = valid.pct_change(fill_method=None)
    # Only evaluate returns between consecutive sessions; never span a missing day.
    consecutive = series.notna() & series.shift().notna()
    returns = returns[consecutive.reindex(returns.index, fill_value=False)].dropna()

    flagged = returns[returns.abs() > OUTLIER_FLAG]
    hard = returns[returns.abs() > OUTLIER_HARD]
    # A volatility index (^VIX, ^VIX3M) can legitimately more than double in a day (2018-02-05),
    # so the hard threshold guards tradeable prices only; index spikes stay warnings.
    hard_applies = not name.startswith("^")
    n_hard = len(hard) if hard_applies else 0
    report["return_outliers"] = {
        "flag_threshold": OUTLIER_FLAG,
        "hard_threshold": OUTLIER_HARD,
        "flagged_count": int(len(flagged)),
        "hard_count": int(len(hard)),
        "hard_threshold_enforced": hard_applies,
        "flagged": [{"date": str(d.date()), "return": float(r)} for d, r in flagged.items()][
            :LIST_CAP
        ],
    }
    if len(flagged) - n_hard:
        issues.append(
            _issue(
                "warning",
                "return_outliers",
                f"{len(flagged) - n_hard} daily returns beyond +/-{OUTLIER_FLAG:.0%}"
                + ("" if hard_applies else f" (incl. {len(hard)} beyond +/-{OUTLIER_HARD:.0%})"),
            )
        )
    if n_hard:
        issues.append(
            _issue(
                "error",
                "return_outliers",
                f"{n_hard} daily returns beyond +/-{OUTLIER_HARD:.0%}",
            )
        )

    splits = []
    for day, ret in flagged.items():
        k = _split_like(1 + ret)
        if k is not None:
            splits.append({"date": str(day.date()), "return": float(ret), "ratio_like": k})
    report["suspected_splits"] = splits
    if splits:
        issues.append(
            _issue("warning", "suspected_splits", f"{len(splits)} jumps match a split ratio")
        )

    runs = _stale_runs(valid, STALE_FLAG_RUN)
    longest = max((r["length"] for r in runs), default=0)
    report["stale_prices"] = {
        "min_run": STALE_FLAG_RUN,
        "runs": runs[:LIST_CAP],
        "longest": longest,
    }
    if longest >= STALE_HARD_RUN:
        issues.append(_issue("error", "stale_prices", f"price unchanged for {longest} sessions"))
    elif runs:
        issues.append(
            _issue(
                "warning",
                "stale_prices",
                f"{len(runs)} runs of >= {STALE_FLAG_RUN} identical prices",
            )
        )

    report["issues"] = issues
    return report


def run_validation(
    *,
    cache_dir: Path | None = None,
    out_path: Path | None = None,
    config: LabConfig | None = None,
) -> dict:
    """Validate every cached series, write the report, raise on hard errors."""
    directory = cache_dir or cache.cache_dir()
    names = cache.cached_names(directory)
    if not names:
        raise DataQualityError(f"no cached series in {directory}; run `lab data pull`")
    frame = load_prices(names, "train", cache_dir=directory, config=config)  # verifies hashes
    series_reports = {}
    for name in names:
        report = check_series(name, frame[name])
        meta = cache.read_meta(directory, name)
        report["alignment"] = {
            kind: sum(e.get("count", 1) for e in meta.get("alignment_log", []) if e["kind"] == kind)
            for kind in ("missing", "forward_fill", "dropped_non_session")
        }
        report["content_hash"] = meta["content_hash"]
        series_reports[name] = report

    errors = [
        {"series": n, **i}
        for n, r in series_reports.items()
        for i in r["issues"]
        if i["severity"] == "error"
    ]
    result = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "passed": not errors,
        "hard_error_count": len(errors),
        "warning_count": sum(
            i["severity"] == "warning" for r in series_reports.values() for i in r["issues"]
        ),
        "hard_errors": errors,
        "series": series_reports,
    }
    out_path = out_path or cache.results_dir() / "data_quality.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    if errors:
        summary = "; ".join(f"{e['series']}: {e['check']} ({e['detail']})" for e in errors)
        raise DataQualityError(f"{len(errors)} hard data-quality error(s): {summary}")
    return result
