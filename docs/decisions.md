# Decisions

Running log of design decisions (date, options, choice, reason). This fills in as the project proceeds.

## 2026-09-29: Python version pin

- Options: SPEC Section 2 says 3.11+; captain specified 3.12+.
- Choice: `requires-python >= 3.12`, `.python-version` and CI pinned to 3.12.
- Reason: captain's locked-in decision; supersedes the spec's 3.11+ floor.

## 2026-09-29: `config/thresholds.yaml` access rules in `.claude/settings.json`

- Options: (a) reproduce SPEC Section 8's "deny read ... `config/thresholds.yaml` edits" literally; (b) treat it as a write-deny target.
- Choice: (b). Agents may read thresholds; edits are denied via the `config/**` edit rule. No read-deny on thresholds.
- Reason: the phrasing is misplaced under the read list, and the judge's transparency rules only require that agents cannot edit thresholds. Claude Code file-permission rules only consult `Read(...)` and `Edit(...)` (an `Edit` deny covers Write and other edit tools), so write-deny is expressed as `Edit(...)`. Paths use the `/`-anchored form (project root).

## 2026-09-29: PBO minimum-trials floor

- Options: any positive integer; SPEC Section 6.1 only says it is "configurable".
- Choice: `pbo.min_trials: 50` in `config/thresholds.yaml`.
- Reason: SPEC gives no number. 50 is a placeholder-free but provisional default so CSCV with S = 16 has a meaningful trial matrix; revisit at Milestone 3 when the judge validation tests exist.
