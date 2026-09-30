#!/usr/bin/env bash
# One iteration of the research loop (SPEC Section 9.5). Run by a human, from anywhere.
#
#   scripts/loop.sh [--n-new N] [--sandbox DIR] [--override-block H-XXXX]...
#
# Steps: 1 hypothesis proposes N specs; 2 skeptic pre-run review (stop on block); 3 checkpoint:
# commit the specs; 4 `lab run`; 5 `lab judge`; 6 skeptic post-run review; 7 `lab holdout`, only
# for an advanced hypothesis a human approves at the terminal; 8 report; 9 `lab dashboard build`.
#
# --sandbox DIR runs the whole iteration against an isolated lab root (its own git repo, hypotheses
# dir, ledger and results), so the real ledger and trial count N are untouched. A sandbox run never
# scores the hold-out. Without --sandbox the loop writes the real hypotheses/, ledger/ and results/.
#
# Agents are launched through scripts/loop_tools.py, which logs each invocation (prompt, files
# touched, duration) under logs/. Overrides for tests: LAB_CMD, LOOP_CLAUDE_CMD, LOOP_AUTO_COMMIT
# (sandbox only). LAB_HOLDOUT_KEY is removed from the environment for everything except the
# `lab holdout` call itself, and is never given to an agent.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$REPO"

N_NEW=2
SANDBOX=""
OVERRIDES=()
while [ $# -gt 0 ]; do
  case "$1" in
    --n-new) N_NEW="$2"; shift 2 ;;
    --sandbox) SANDBOX="$2"; shift 2 ;;
    --override-block) OVERRIDES+=("$2"); shift 2 ;;
    -h|--help) sed -n '2,17p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "loop.sh: unknown argument: $1" >&2; exit 2 ;;
  esac
done
case "$N_NEW" in ''|*[!0-9]*|0) echo "loop.sh: --n-new must be a positive integer" >&2; exit 2 ;; esac

LAB_CMD="${LAB_CMD:-uv run lab}"
TOOLS="${LOOP_TOOLS_CMD:-uv run python $REPO/scripts/loop_tools.py}"
HOLDOUT_KEY="${LAB_HOLDOUT_KEY:-}"   # kept aside for the human-approved hold-out step only
unset LAB_HOLDOUT_KEY

if [ -n "$SANDBOX" ]; then
  mkdir -p "$SANDBOX"
  LAB_ROOT="$(cd "$SANDBOX" && pwd -P)"
  mkdir -p "$LAB_ROOT/hypotheses/signals" "$LAB_ROOT/ledger/returns" "$LAB_ROOT/results"
  cp -n "$REPO/hypotheses/H-0000_template.yaml" "$LAB_ROOT/hypotheses/" 2>/dev/null || true
  [ -e "$LAB_ROOT/ledger/trials.jsonl" ] || : > "$LAB_ROOT/ledger/trials.jsonl"
  if ! git -C "$LAB_ROOT" rev-parse --show-toplevel >/dev/null 2>&1 \
     || [ "$(git -C "$LAB_ROOT" rev-parse --show-toplevel)" != "$LAB_ROOT" ]; then
    git -C "$LAB_ROOT" init -q -b main
    git -C "$LAB_ROOT" config user.name "lab-sandbox"
    git -C "$LAB_ROOT" config user.email "sandbox@lab.invalid"
    git -C "$LAB_ROOT" config commit.gpgsign false
    git -C "$LAB_ROOT" add -A
    git -C "$LAB_ROOT" commit -q -m "sandbox baseline"
  fi
  export LAB_HYPOTHESES_DIR="$LAB_ROOT/hypotheses" LAB_LEDGER_DIR="$LAB_ROOT/ledger"
  export LAB_RESULTS_DIR="$LAB_ROOT/results"
  echo "SANDBOX MODE: $LAB_ROOT (real ledger and hypotheses untouched; hold-out is never scored)"
else
  LAB_ROOT="$REPO"
  if [ -n "${LOOP_AUTO_COMMIT:-}" ]; then
    echo "loop.sh: LOOP_AUTO_COMMIT is only allowed with --sandbox" >&2; exit 2
  fi
fi
HYP_DIR="${LAB_HYPOTHESES_DIR:-$REPO/hypotheses}"
RESULTS_DIR="${LAB_RESULTS_DIR:-$LAB_ROOT/results}"
LEDGER_DIR="${LAB_LEDGER_DIR:-$LAB_ROOT/ledger}"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_DIR="${LOOP_LOG_DIR:-$REPO/logs}/loop-$RUN_ID"
mkdir -p "$LOG_DIR"
TODAY="$(date -u +%Y-%m-%d)"
say() { printf '\n== %s\n' "$*"; }
lab() { $LAB_CMD "$@"; }

agent() {  # agent NAME STEP PROMPT_FILE [extra run-agent args]
  local name="$1" step="$2" prompt="$3"; shift 3
  $TOOLS run-agent --agent "$name" --step "$step" --prompt-file "$prompt" \
    --log-dir "$LOG_DIR" --lab-root "$LAB_ROOT" "$@"
}

# "SPEC_PATH SIGNAL_PATH" for one id, so agents never have to discover files (Glob skips gitignored dirs)
spec_of() {
  $TOOLS spec-files "$1" | python3 -c \
    'import json,sys; [print(f["spec"], f["signal"]) for f in json.load(sys.stdin)]'
}
NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

overridden() { local x; for x in ${OVERRIDES[@]+"${OVERRIDES[@]}"}; do [ "$x" = "$1" ] && return 0; done; return 1; }

# ---------------------------------------------------------------- 1. hypothesis proposes specs
say "1/9 hypothesis proposes $N_NEW spec(s)"
IDS=($($TOOLS next-ids "$N_NEW"))
SUMMARY="$(lab ledger summary)"
cat > "$LOG_DIR/prompt-hypothesis.txt" <<PROMPT
Propose $N_NEW new hypothesis specs with signal modules, using exactly these ids: ${IDS[*]}.
Lab root: $LAB_ROOT (write only under $LAB_ROOT/hypotheses/ and $LAB_ROOT/hypotheses/signals/).
Today's date (for registered_at): $TODAY.
Signal modules go in hypotheses/signals/hNNNN_<slug>.py; set signal_module in the spec to that path
relative to the lab root, e.g. hypotheses/signals/h0001_<slug>.py.
Earlier specs are in $HYP_DIR. Ledger summary (train split only):
$SUMMARY
PROMPT
agent hypothesis 01-hypothesis "$LOG_DIR/prompt-hypothesis.txt" \
  --expect-glob 'hypotheses/*.yaml' --expect-glob 'hypotheses/signals/*.py'
SPECS_JSON="$($TOOLS spec-files "${IDS[@]}")"
echo "$SPECS_JSON"

# ---------------------------------------------------------------- 2. skeptic pre-run review
say "2/9 skeptic pre-run review"
CLEARED=()
for id in "${IDS[@]}"; do
  cat > "$LOG_DIR/prompt-skeptic-pre-$id.txt" <<PROMPT
Pre-run review of $id. Lab root: $LAB_ROOT. Append your review to $RESULTS_DIR/$id/review.md
(section title "Pre-run review", last line "Recommendation (pre-run): clear|block"). Time now: $NOW.
Spec and signal module (read both): $(spec_of "$id")
Earlier specs are in $HYP_DIR. Repo code, tests and config are under $REPO (read-only for you).
Run: uv run lab leakage $id
PROMPT
  agent skeptic "02-skeptic-pre-$id" "$LOG_DIR/prompt-skeptic-pre-$id.txt" \
    --expect-glob 'results/*/review.md' \
    --allowed-tool 'Bash(uv run pytest:*)' --allowed-tool 'Bash(uv run lab leakage:*)'
  status="$($TOOLS review-status "$RESULTS_DIR/$id/review.md" pre)"
  echo "$id: skeptic pre-run recommendation: $status"
  if [ "$status" = "clear" ]; then
    CLEARED+=("$id")
  elif overridden "$id"; then
    if [ -t 0 ]; then
      read -r -p "Type 'override $id' to run $id despite the skeptic's block: " answer
      [ "$answer" = "override $id" ] && CLEARED+=("$id") || echo "$id stays blocked"
    else
      echo "$id: override needs an interactive terminal; stays blocked"
    fi
  else
    echo "$id: BLOCKED by the skeptic (or no recommendation). Read $RESULTS_DIR/$id/review.md;"
    echo "     rerun with --override-block $id to run it anyway."
  fi
done
if [ ${#CLEARED[@]} -eq 0 ]; then
  echo "No spec cleared the skeptic; stopping before any run."
  exit 1
fi

# ---------------------------------------------------------------- 3. checkpoint: commit the specs
say "3/9 checkpoint: commit the specs (pre-registration requires a commit before the run)"
FILES=()
for id in "${CLEARED[@]}"; do
  FILES+=($($TOOLS spec-files "$id" | python3 -c \
    'import json,sys; [print(f["spec"], f["signal"]) for f in json.load(sys.stdin)]'))
done
REG_REPO="$(git -C "$HYP_DIR" rev-parse --show-toplevel)"
git -C "$REG_REPO" status --short -- "${FILES[@]}"
if [ -n "${LOOP_AUTO_COMMIT:-}" ]; then
  echo "LOOP_AUTO_COMMIT set (sandbox): committing without a prompt"
elif [ -t 0 ]; then
  read -r -p "Review the files above. Type 'commit' to register ${CLEARED[*]}: " answer
  [ "$answer" = "commit" ] || { echo "Checkpoint declined; nothing committed or run."; exit 1; }
else
  echo "Checkpoint needs a human at a terminal; nothing committed or run." >&2
  exit 1
fi
git -C "$REG_REPO" add -- "${FILES[@]}"
git -C "$REG_REPO" commit -q -m "register ${CLEARED[*]}" -- "${FILES[@]}"
git -C "$REG_REPO" log -1 --format='committed %h %cI'
sleep 1  # the commit date must be strictly before the run time (second-level commit dates)

# ---------------------------------------------------------------- 4/5. run and judge
FAILED=0
JUDGED=()
say "4/9 lab run  and  5/9 lab judge"
for id in "${CLEARED[@]}"; do
  if lab run "$id" && lab judge "$id"; then
    JUDGED+=("$id")
    echo "$id: train verdict: $($TOOLS verdict "$id")"
  else
    echo "$id: run or judge failed; see the output above" >&2
    FAILED=1
  fi
done

# ---------------------------------------------------------------- 6. skeptic post-run review
say "6/9 skeptic post-run review"
for id in ${JUDGED[@]+"${JUDGED[@]}"}; do
  cat > "$LOG_DIR/prompt-skeptic-post-$id.txt" <<PROMPT
Post-run review of $id. Lab root: $LAB_ROOT. Read $RESULTS_DIR/$id/verdict.json and the trials
for $id in $LEDGER_DIR/trials.jsonl. Append your review to $RESULTS_DIR/$id/review.md
(section title "Post-run review", last line "Recommendation (post-run): clear|block"). Time now: $NOW.
Spec and signal module: $(spec_of "$id"). Repo code, tests and config are under $REPO (read-only).
PROMPT
  agent skeptic "06-skeptic-post-$id" "$LOG_DIR/prompt-skeptic-post-$id.txt" \
    --expect-glob 'results/*/review.md' \
    --allowed-tool 'Bash(uv run pytest:*)' --allowed-tool 'Bash(uv run lab leakage:*)'
  echo "$id: skeptic post-run recommendation: $($TOOLS review-status "$RESULTS_DIR/$id/review.md" post)"
done

# ---------------------------------------------------------------- 7. hold-out (human only)
say "7/9 hold-out (human decision; interactive terminal only)"
ADVANCED=()
for id in ${JUDGED[@]+"${JUDGED[@]}"}; do
  [ "$($TOOLS verdict "$id")" = "advance" ] && ADVANCED+=("$id")
done
if [ ${#ADVANCED[@]} -eq 0 ]; then
  echo "No hypothesis advanced; the hold-out is not scored."
elif [ -n "$SANDBOX" ]; then
  echo "Sandbox run: advanced ${ADVANCED[*]}; the hold-out is never scored from a sandbox."
elif [ ! -t 0 ] || [ ! -t 1 ]; then
  echo "Advanced: ${ADVANCED[*]}. No interactive terminal, so the hold-out is NOT scored."
  echo "Review the ledger diff, then run \`lab holdout <id>\` yourself, in your own shell."
else
  for id in "${ADVANCED[@]}"; do
    echo "$id advanced on the train split. The hold-out can be scored once and cannot be undone."
    read -r -p "Type 'holdout $id' to score it now (anything else skips): " answer
    if [ "$answer" = "holdout $id" ]; then
      LAB_HOLDOUT_KEY="$HOLDOUT_KEY" lab holdout "$id" || FAILED=1
    else
      echo "$id: hold-out skipped"
    fi
  done
fi

# ---------------------------------------------------------------- 8. report
say "8/9 report"
for id in ${JUDGED[@]+"${JUDGED[@]}"}; do
  cat > "$LOG_DIR/prompt-report-$id.txt" <<PROMPT
Write the report for $id. Lab root: $LAB_ROOT. Sources: $(spec_of "$id" | cut -d' ' -f1) (spec), $RESULTS_DIR/$id/verdict.json,
$RESULTS_DIR/$id/review.md, $LEDGER_DIR/trials.jsonl. Write only $RESULTS_DIR/$id/report.md.
PROMPT
  agent report "08-report-$id" "$LOG_DIR/prompt-report-$id.txt" --expect-glob 'results/*/report.md'
done

# ---------------------------------------------------------------- 9. dashboard
say "9/9 lab dashboard build"
lab dashboard build || FAILED=1

say "iteration finished (logs: $LOG_DIR)"
lab ledger summary
exit "$FAILED"
