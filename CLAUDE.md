# lev-etf-lab
Read SPEC.md first. Rules that always apply:
- Ask clarifying questions and present a plan with tradeoffs before writing code.
- Numbers and verdicts come from core/ code only. Never estimate or hand-write results.
- Never read, list, or reference data/holdout.enc or results/holdout/.
- Never edit config/, core/judge/, ledger/, or .claude/settings.json.
- Every backtest goes through `lab run` so it is counted in the ledger.
- Signals use only information available at the close of day t.
- One milestone at a time; check acceptance criteria before moving on.
