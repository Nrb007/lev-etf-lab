# lev-etf-lab

Hypothesis-driven research system for leveraged tech ETF timing signals. See SPEC.md for the full build specification.

## Dashboard

A static dashboard (`dashboard/`) renders `results/`. Build it with `uv run lab dashboard build` (needs Node.js); the output is `dashboard/dist/`. It is unlisted and asks search engines not to index it; that is not access control (see `docs/decisions.md`).
