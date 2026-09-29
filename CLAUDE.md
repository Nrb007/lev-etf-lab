# lev-etf-lab
Read SPEC.md first. Rules that always apply:
- Ask clarifying questions and present a plan with tradeoffs before writing code.
- Numbers and verdicts come from core/ code only. Never estimate or hand-write results.
- Never read, list, or reference data/holdout.enc or results/holdout/.
- Autonomous research-loop agents never edit config/, core/judge/, ledger/, or .claude/. Supervised construction sessions may, through the normal PR review; nobody edits .claude/settings.json without the captain's approval.
- Every backtest goes through `lab run` so it is counted in the ledger.
- Signals use only information available at the close of day t.
- One milestone at a time; check acceptance criteria before moving on.
