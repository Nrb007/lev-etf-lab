## Pre-run review - H-0002 - 2026-09-29T00:00:00Z

Findings:
- Spec and signal not reviewed: `hypotheses/H-0002_*.yaml` and its signal module could not be opened. My tools cannot list directories and the file suffix is unknown, and reading the directory failed (EISDIR). So mechanism, parameter and grid justification, universe selection, `notes_on_prior_trials`, cost assumptions, holdout_start usage and near-duplicate checks were NOT checked.
- `uv run lab leakage H-0002` (run from the repo root, not the sandbox): "no leakage across 9 grid points (25 truncation dates each)". This only shows no truncation-sensitivity in the engine self-test. It does not cover a same-day-close execution assumption, a weak mechanism or the grid size. The sandbox may also not be the lab root that command used, so treat it as weak evidence.
- The grid has 9 points, and each one raises N. I can't judge whether that is justified without the spec.
- `ledger/trials.jsonl` is empty, so there are no prior trials for H-0002 and nothing to cross-check for peeking.
- `results/H-0002/review.md` did not exist before this review.

Recommendation (pre-run): block
