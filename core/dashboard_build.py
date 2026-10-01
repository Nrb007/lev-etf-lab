"""``lab dashboard build``: stage the published results, run the Vite build, check the output.

The site is static and reads JSON from ``results/``. Only an explicit allow-list is copied next to
the page (``index.json``, ``judge_validation.json`` and each ``H-XXXX/detail.json``); the rest of
``results/`` is never published (the detail files already carry the hold-out pass/fail and date
that the dashboard is allowed to show, and nothing more).

Output: ``dashboard/dist/`` (gitignored). It is a plain static folder: serve it from any host. The
GitHub Pages workflow (``.github/workflows/pages.yml``) builds it with ``--skip-export`` from the
committed ``results/`` and deploys that folder.
"""

from __future__ import annotations

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
PUBLISHED_NAME = re.compile(r"^(index\.json|judge_validation\.json|H-\d{4}/detail\.json)$")
NOINDEX = re.compile(r"<meta[^>]+name=[\"']robots[\"'][^>]+noindex", re.I)


class BuildError(RuntimeError):
    """The dashboard could not be built or failed its post-build checks."""


def stage_data(results: Path, stage: Path = STAGE_DIR) -> list[str]:
    """Copy the allow-listed JSON into ``stage`` (replacing it) and return the published paths."""
    index = results / "index.json"
    if not index.exists():
        raise BuildError(f"{index} does not exist; run `lab dashboard export` first")
    validation = results / "judge_validation.json"
    if not validation.exists():  # e.g. an isolated demo sandbox: use the repo's recorded validation
        validation = REPO_ROOT / "results" / "judge_validation.json"
    if not validation.exists():
        raise BuildError("results/judge_validation.json does not exist (see docs/decisions.md)")
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    copied = []
    for src, name in [(index, "index.json"), (validation, "judge_validation.json")]:
        shutil.copy(src, stage / name)
        copied.append(name)
    for detail in sorted(results.glob("H-*/detail.json")):
        if not ID_DIR.match(detail.parent.name):
            continue
        target = stage / detail.parent.name / "detail.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(detail, target)
        copied.append(f"{detail.parent.name}/detail.json")
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
