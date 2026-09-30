## Pre-run review - H-0001 - 2026-09-29T00:00:00Z

Findings:
- `uv run lab leakage H-0001` reported: "no leakage across 12 grid points (25 truncation dates each)". This only covers the signal's dependence on future rows. It says nothing about same-day-close execution, mechanism, grid size, cost assumptions, universe choice or duplicates.
- I could not read `hypotheses/H-0001_*.yaml` or its signal module. The spec filename has a suffix I could not discover. My Bash is limited to pytest and leakage, I have no directory-listing tool, and the guessed path `hypotheses/H-0001.yaml` does not exist. I also could not read `config/lab.yaml` (the path under the sandbox lab root was not found), so `holdout_start` is unchecked.
- Not reviewed, so no assurance given: mechanism quality, parameter and grid justification (the leakage test implies a 12-point grid, which is unjustified until the spec is read), execution timing, cost realism, turnover versus mechanism, post-hoc universe or period selection, `notes_on_prior_trials` peeking, use of data on or after `holdout_start`, and near-duplicates of earlier specs.

Recommendation (pre-run): block
