"""Dashboard data export and build staging (Milestone 6)."""

import json
import math

import pandas as pd
import pytest
from typer.testing import CliRunner

from core import dashboard_build, dashboard_export
from core.cli import app
from core.ledger import ledger
from tests.prereg_helpers import init_repo, write_spec

runner = CliRunner()


@pytest.fixture
def lab_env(pulled, monkeypatch, tmp_path):
    monkeypatch.setenv("LAB_DATA_DIR", str(pulled["tmp_path"]))
    monkeypatch.setenv("LAB_LEDGER_DIR", str(tmp_path / "ledger"))
    monkeypatch.setenv("LAB_RESULTS_DIR", str(tmp_path / "results"))
    repo = init_repo(tmp_path / "repo")
    monkeypatch.setenv("LAB_HYPOTHESES_DIR", str(repo / "hypotheses"))
    write_spec(repo)
    assert runner.invoke(app, ["run", "H-9999"]).exit_code == 0
    assert runner.invoke(app, ["judge", "H-9999"]).exit_code == 0
    return tmp_path


def test_detail_carries_curves_grid_verdict_and_text(lab_env):
    results = lab_env / "results" / "H-9999"
    (results / "report.md").write_text("## Why\n\nA report.\n")
    (results / "review.md").write_text("Pre-run review\n\nRecommendation (pre-run): clear\n")
    detail = dashboard_export.export_hypothesis("H-9999")
    assert json.loads((results / "detail.json").read_text()) == detail
    assert detail["title"] and detail["mechanism"].startswith("Test-only")
    assert detail["report_md"].startswith("## Why")
    assert detail["reviews"] == {"pre": "clear", "post": None}
    assert [g["trial"] for g in detail["grid"]] == [
        "H-9999-000001",
        "H-9999-000002",
        "H-9999-000003",
    ]
    assert detail["verdict"]["train_verdict"] == "reject" and detail["holdout"] is None
    rows = detail["curves"]
    assert rows[0]["date"] < rows[-1]["date"] and len(rows) < 200
    for name in ("strategy", "buy_and_hold", "half_cash"):
        assert all(r[f"drawdown_{name}"] <= 0 for r in rows)
        assert all(r[f"equity_{name}"] > 0 for r in rows)


def test_equity_curve_ends_where_the_ledger_returns_compound_to(lab_env):
    detail = dashboard_export.export_hypothesis("H-9999")
    trial = next(t for t in ledger.read_trials() if t["trial_id"] == detail["chosen_trial"])
    returns = pd.read_parquet(ledger.ledger_dir() / trial["returns_path"])["return"]
    assert detail["curves"][-1]["equity_strategy"] == pytest.approx((1 + returns).prod())
    assert detail["curves"][-1]["date"] == str(returns.index[-1].date())


def test_drawdown_keeps_the_trough_inside_each_sampled_block():
    idx = pd.bdate_range("2020-01-01", periods=12)
    ret = pd.Series([0.0] * 12, index=idx)
    ret.iloc[2] = -0.5  # a one-day crash that the sampled dates (0, 5, 10, 11) would skip over
    rows = dashboard_export.curves(ret, {"buy_and_hold": ret})
    assert min(r["drawdown_strategy"] for r in rows) == pytest.approx(-0.5)


def test_undefined_metrics_become_null_not_nan():
    cleaned = dashboard_export._clean(
        {"a": math.nan, "b": [math.inf, 1.0], "c": {"d": float("-inf")}}
    )
    assert cleaned == {"a": None, "b": [None, 1.0], "c": {"d": None}}
    json.dumps(cleaned, allow_nan=False)


def test_index_counts_the_funnel_and_trials(lab_env):
    (lab_env / "results" / "H-9999" / "review.md").write_text("Recommendation (pre-run): clear\n")
    index = dashboard_export.export_all()
    assert index["n_trials"] == 3
    assert index["funnel"] == {
        "proposed": 1,
        "passed_skeptic": 1,
        "passed_judge": 0,
        "passed_holdout": 0,
    }
    [row] = index["hypotheses"]
    assert row["id"] == "H-9999" and row["train_verdict"] == "reject" and "pbo" in row["reasons"]
    assert json.loads((lab_env / "results" / "index.json").read_text()) == index


def test_rejected_hypotheses_are_in_the_index(lab_env):
    index = dashboard_export.export_all()
    assert [r["train_verdict"] for r in index["hypotheses"]] == ["reject"]


def test_review_recommendation_needs_the_exact_last_line_format(lab_env):
    path = lab_env / "results" / "H-9999" / "review.md"
    path.write_text(
        "Pre-run review\nRecommendation (pre-run): block\n\nPost-run review\n"
        "Recommendation (post-run): **clear**\nRecommendation (pre-run): clear\n"
    )
    assert dashboard_export.review_recommendations("H-9999") == {"pre": "clear", "post": "clear"}
    path.write_text("no recommendation here\n")
    assert dashboard_export.review_recommendations("H-9999") == {"pre": None, "post": None}


def test_holdout_shows_only_pass_fail_and_the_date(lab_env):
    assert dashboard_export._holdout_status("H-9999") is None
    ledger.reserve_holdout_attempt({"hypothesis_id": "H-9999", "trial_id": "x"})
    assert dashboard_export._holdout_status("H-9999") is None  # started, not finished
    ledger.record_holdout_outcome("H-9999", "fail")
    status = dashboard_export._holdout_status("H-9999")
    assert set(status) == {"verdict", "scored_on"} and status["verdict"] == "fail"
    assert len(status["scored_on"]) == 10
    detail = dashboard_export.export_hypothesis("H-9999")
    assert detail["holdout"] == status


def test_export_requires_a_verdict(lab_env):
    (lab_env / "results" / "H-9999" / "verdict.json").unlink()
    with pytest.raises(dashboard_export.RunError, match="lab judge"):
        dashboard_export.export_hypothesis("H-9999")


def test_data_source_is_reported_from_the_cache_sidecar(lab_env):
    index = dashboard_export.export_all()
    assert index["data_source"]["simulated"] is False


def test_cli_export_command(lab_env):
    result = runner.invoke(app, ["dashboard", "export", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["funnel"]["proposed"] == 1


def _write_index(directory, ids):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "index.json").write_text(json.dumps({"hypotheses": [{"id": i} for i in ids]}))
    for hid in ids:
        (directory / hid).mkdir(exist_ok=True)
        (directory / hid / "detail.json").write_text(json.dumps({"id": hid}))
        (directory / hid / "verdict.json").write_text("{}")
        (directory / hid / "review.md").write_text("x")


def _results(tmp_path, *, demo=("H-0001", "H-0003")):
    res = tmp_path / "res"
    (res / "holdout").mkdir(parents=True)
    (res / "holdout" / "H-0001.json").write_text("{}")
    _write_index(res, ["H-0001"])
    if demo:
        _write_index(res / "demo", list(demo))
    (res / "judge_validation.json").write_text("{}")
    (res / "data_quality.json").write_text("{}")
    return res


def _staged(stage):
    return sorted(p.relative_to(stage).as_posix() for p in stage.rglob("*") if p.is_file())


def test_stage_data_publishes_only_what_the_indexes_list(tmp_path):
    stage = tmp_path / "stage"
    copied = dashboard_build.stage_data(_results(tmp_path), stage)
    files = _staged(stage)
    assert files == [
        "H-0001/detail.json",
        "demo/H-0001/detail.json",
        "demo/H-0003/detail.json",
        "demo/index.json",
        "index.json",
        "judge_validation.json",
    ]
    assert sorted(copied) == files
    assert json.loads((stage / "demo" / "H-0003" / "detail.json").read_text()) == {"id": "H-0003"}


def test_stage_data_never_publishes_orphans(tmp_path):
    res = _results(tmp_path)
    (res / "H-0042").mkdir()
    (res / "H-0042" / "detail.json").write_text("{}")
    (res / "demo" / "H-0042").mkdir()
    (res / "demo" / "H-0042" / "detail.json").write_text("{}")
    (res / "demo" / "notes.json").write_text("{}")
    stage = tmp_path / "stage"
    dashboard_build.stage_data(res, stage)
    assert not any("H-0042" in f or "notes" in f for f in _staged(stage))


def test_stage_data_without_a_demo_publishes_the_real_results_only(tmp_path):
    stage = tmp_path / "stage"
    dashboard_build.stage_data(_results(tmp_path, demo=()), stage)
    assert _staged(stage) == ["H-0001/detail.json", "index.json", "judge_validation.json"]


def test_an_empty_real_index_is_valid(tmp_path):
    res = _results(tmp_path)
    _write_index(res, [])
    stage = tmp_path / "stage"
    dashboard_build.stage_data(res, stage)
    assert "index.json" in _staged(stage) and "H-0001/detail.json" not in _staged(stage)


@pytest.mark.parametrize("where", [".", "demo"])
def test_a_listed_id_without_a_detail_file_is_a_build_error(tmp_path, where):
    res = _results(tmp_path)
    (res / where / "H-0001" / "detail.json").unlink()
    with pytest.raises(dashboard_build.BuildError, match="detail.json is missing"):
        dashboard_build.stage_data(res, tmp_path / "stage")


def test_a_listed_id_that_is_not_a_hypothesis_id_is_a_build_error(tmp_path):
    res = _results(tmp_path)
    _write_index(res, ["../demo"])
    with pytest.raises(dashboard_build.BuildError, match="malformed"):
        dashboard_build.stage_data(res, tmp_path / "stage")


def test_stage_data_replaces_stale_files(tmp_path):
    stage = tmp_path / "stage"
    (stage / "H-0042").mkdir(parents=True)
    (stage / "H-0042" / "detail.json").write_text("stale")
    dashboard_build.stage_data(_results(tmp_path), stage)
    assert not (stage / "H-0042").exists()


def test_stage_data_needs_an_index(tmp_path):
    res = _results(tmp_path)
    (res / "index.json").unlink()
    with pytest.raises(dashboard_build.BuildError, match="lab dashboard export"):
        dashboard_build.stage_data(res, tmp_path / "stage")


def test_export_never_reads_or_writes_the_demo_subtree(lab_env):
    demo = lab_env / "results" / "demo"
    _write_index(demo, ["H-9999"])  # same id as the real hypothesis, to prove no collision
    (demo / "H-9999" / "detail.json").write_text('{"demo": true}')
    before = {p: p.read_bytes() for p in demo.rglob("*") if p.is_file()}
    index = dashboard_export.export_all()
    assert [r["id"] for r in index["hypotheses"]] == ["H-9999"]
    assert {p: p.read_bytes() for p in demo.rglob("*") if p.is_file()} == before
    real = json.loads((lab_env / "results" / "H-9999" / "detail.json").read_text())
    assert real != {"demo": True} and real["id"] == "H-9999"


def _dist(tmp_path, *, meta=True, robots=True):
    dist = tmp_path / "dist"
    (dist / "data" / "H-0001").mkdir(parents=True)
    (dist / "data" / "demo" / "H-0001").mkdir(parents=True)
    (dist / "data" / "index.json").write_text("{}")
    (dist / "data" / "H-0001" / "detail.json").write_text("{}")
    (dist / "data" / "demo" / "index.json").write_text("{}")
    (dist / "data" / "demo" / "H-0001" / "detail.json").write_text("{}")
    tag = '<meta name="robots" content="noindex, nofollow">' if meta else ""
    (dist / "index.html").write_text(f"<html><head>{tag}</head></html>")
    if robots:
        (dist / "robots.txt").write_text("User-agent: *\nDisallow: /\n")
    return dist


def test_check_output_passes_for_an_unlisted_site(tmp_path):
    dashboard_build.check_output(_dist(tmp_path))


def test_check_output_refuses_a_site_without_noindex_or_robots(tmp_path):
    with pytest.raises(dashboard_build.BuildError, match="noindex"):
        dashboard_build.check_output(_dist(tmp_path / "a", meta=False))
    with pytest.raises(dashboard_build.BuildError, match="robots.txt"):
        dashboard_build.check_output(_dist(tmp_path / "b", robots=False))


@pytest.mark.parametrize("extra", ["extra.json", "demo/verdict.json", "demo/H-0001/review.md"])
def test_check_output_refuses_unexpected_published_data(tmp_path, extra):
    dist = _dist(tmp_path)
    (dist / "data" / extra).write_text("{}")
    with pytest.raises(dashboard_build.BuildError, match="unexpected files"):
        dashboard_build.check_output(dist)
