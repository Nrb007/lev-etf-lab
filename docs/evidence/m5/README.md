# Milestone 5 evidence

Recorded in the M5 build session (2026-09-29/30), Claude Code 2.1.285, agents on `sonnet` (`LOOP_AGENT_MODEL`). Nothing here is a research result: the loop ran against an isolated sandbox (`scripts/loop.sh --sandbox demo/sandbox`), so the real `ledger/trials.jsonl` and N are unchanged (the file is still empty and `git diff ledger/` is empty).

## `iteration/`: one full loop iteration, end to end

`loop-run.log` is the driver's output for all nine steps with 2 new hypotheses:

1. `hypothesis` wrote 2 specs and 2 signal modules (`sandbox/hypotheses/`).
2. `skeptic` pre-run reviews: both `clear` (`sandbox/results/H-000x/review.md`).
3. Checkpoint: specs committed in the sandbox repo (`sandbox/git-log.txt`). `LOOP_AUTO_COMMIT=1` was set because the session has no terminal; it is refused outside `--sandbox`, so the human prompt stays mandatory for real specs.
4. `lab run`: 9 grid points each, N = 9 then 18 (sandbox `sandbox/ledger/trials.jsonl`).
5. `lab judge`: both `reject` (H-0001: spa, pbo, regime; H-0002: spa, pbo, permutation, sensitivity, stress, regime). PBO is "insufficient trials" by construction with so few trials.
6. `skeptic` post-run reviews: both `block` (they read the verdicts and the trials).
7. Hold-out: not reached (no advance; a sandbox never scores it anyway).
8. `report` wrote `sandbox/results/H-000x/report.md` for each.
9. `lab dashboard build`: the Milestone 6 stub.

`logs/` holds what the driver recorded for each agent invocation: the prompt, command, duration, exit code, cost, permission denials, and the files created, modified or deleted (`01-hypothesis.json` shows exactly four files created and none outside its scope; `unexpected_files` is empty for every step). The denials in the skeptic and report logs are the agents trying a `cd ... && ...` or a `grep` through Bash, which the command hook refuses.

## `first-attempt-blocked/`: the gate failing closed

The first run of the driver gave the skeptic no file paths, and its Glob and Bash could not find the spec (the demo dir is gitignored). It said so in its review, could not check the spec, and recommended `block` for both; the driver stopped before any run. The driver now passes exact spec and signal paths in the prompts. Kept because it is the "block stops `lab run`" behavior observed with real agents.

## `permission-probes.json`: real agents told to break their scope

`LAB_LIVE_AGENT_TESTS=1 uv run pytest tests/agents/test_live_agents.py` gives each of the four agents a task to write files it must not write (the judge, `config/`, `ledger/`, another agent's files) and one file it may write. For every agent the forbidden files do not exist afterwards, the hook denials are in `permission_denials`, and the allowed file was written. The deterministic version of the same attempts (the hook commands from the agent files, fed tool-call JSON) runs in CI: `tests/agents/test_permission_violations.py`.
