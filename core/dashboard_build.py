"""``lab dashboard build``: stage the published results, run the Vite build, check the output.

The site is static and reads JSON from ``results/``. Only what an index lists is copied next to
the page: ``results/index.json`` with the ``H-XXXX/detail.json`` of its ids, the simulated demo
(``results/demo/index.json`` with its ids, staged under ``data/demo/``) and
``judge_validation.json``. Nothing is globbed, so an orphaned file is never published (the detail
files already carry the hold-out pass/fail and date that the dashboard is allowed to show, and
nothing more).

Output: ``dashboard/dist/`` (gitignored). It is a plain static folder: serve it from any host. The
GitHub Pages workflow (``.github/workflows/pages.yml``) builds it with ``--skip-export`` from the
committed ``results/`` and deploys that folder.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from core.dashboard_export import export_all
from core.data import cache

REPO_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_DIR = REPO_ROOT / "dashboard"
STAGE_DIR = DASHBOARD_DIR / "public" / "data"
DIST_DIR = DASHBOARD_DIR / "dist"
ID_DIR = re.compile(r"^H-\d{4}$")
DEMO_DIR = "demo"
PUBLISHED_NAME = re.compile(
    r"^(index\.json|judge_validation\.json|H-\d{4}/detail\.json"
    r"|demo/index\.json|demo/H-\d{4}/detail\.json)$"
)
NOINDEX = re.compile(r"<meta[^>]+name=[\"']robots[\"'][^>]+noindex", re.I)


class BuildError(RuntimeError):
    """The dashboard could not be built or failed its post-build checks."""


def _stage_index(source: Path, stage: Path, prefix: str) -> list[str]:
    """Copy ``source/index.json`` and the detail file of every id it lists; nothing else."""
    index = source / "index.json"
    rows = json.loads(index.read_text()).get("hypotheses", [])
    ids = [row["id"] for row in rows]
    bad = [i for i in ids if not ID_DIR.match(str(i))]
    if bad:
        raise BuildError(f"{index} lists malformed hypothesis ids: {bad}")
    missing = [i for i in ids if not (source / i / "detail.json").exists()]
    if missing:
        raise BuildError(f"{index} lists {missing} but their detail.json is missing")
    shutil.copy(index, stage / prefix / "index.json")
    copied = [f"{prefix}index.json"]
    for hid in ids:
        target = stage / prefix / hid / "detail.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(source / hid / "detail.json", target)
        copied.append(f"{prefix}{hid}/detail.json")
    return copied


def stage_data(results: Path, stage: Path = STAGE_DIR) -> list[str]:
    """Copy the published JSON into ``stage`` (replacing it) and return the published paths."""
    index = results / "index.json"
    if not index.exists():
        raise BuildError(f"{index} does not exist; run `lab dashboard export` first")
    validation = results / "judge_validation.json"
    if not validation.exists():  # e.g. an isolated sandbox: use the repo's recorded validation
        validation = REPO_ROOT / "results" / "judge_validation.json"
    if not validation.exists():
        raise BuildError("results/judge_validation.json does not exist (see docs/decisions.md)")
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    copied = _stage_index(results, stage, "")
    shutil.copy(validation, stage / "judge_validation.json")
    copied.append("judge_validation.json")
    if (results / DEMO_DIR / "index.json").exists():
        (stage / DEMO_DIR).mkdir()
        copied += _stage_index(results / DEMO_DIR, stage, f"{DEMO_DIR}/")
    return copied


def _npm(*args: str) -> None:
    try:
        subprocess.run(["npm", *args], cwd=DASHBOARD_DIR, check=True)
    except FileNotFoundError as exc:
        raise BuildError("npm not found: the dashboard build needs Node.js (npm)") from exc
    except subprocess.CalledProcessError as exc:
        raise BuildError(f"npm {' '.join(args)} failed (exit {exc.returncode})") from exc


def check_output(dist: Path = DIST_DIR) -> None:
    """The built site must keep itself out of search indexes (unlisted, not access-controlled)."""
    index = dist / "index.html"
    if not index.exists():
        raise BuildError(f"{index} was not produced")
    if not NOINDEX.search(index.read_text()):
        raise BuildError("built index.html has no robots noindex meta tag")
    robots = dist / "robots.txt"
    if not robots.exists() or "Disallow: /" not in robots.read_text():
        raise BuildError("built site has no robots.txt disallowing all")
    stray = [
        p.relative_to(dist / "data").as_posix()
        for p in (dist / "data").rglob("*")
        if p.is_file() and not PUBLISHED_NAME.match(p.relative_to(dist / "data").as_posix())
    ]
    if stray:
        raise BuildError(f"unexpected files in the published data folder: {stray}")


def build(*, skip_export: bool = False) -> dict:
    """Export (unless skipped), stage the JSON, build with Vite, check the output."""
    if not skip_export:
        export_all()
    published = stage_data(cache.results_dir())
    if not (DASHBOARD_DIR / "node_modules").exists():
        _npm("ci")
    _npm("run", "build")
    check_output()
    return {"output_dir": str(DIST_DIR), "published": published}
