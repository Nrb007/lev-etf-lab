#!/usr/bin/env bash
# Populate the dashboard's demo `results/` by running the real pipeline on an isolated sandbox
# (Milestone 6). Steps follow scripts/loop.sh (skeptic pre-run review, `lab run`, `lab judge`,
# skeptic post-run review, `report` agent), but the four specs are written by hand (not proposed by
# the `hypothesis` agent) because the point is a known mix of outcomes on a simulated universe.
#
#   docs/evidence/m6/run-demo.sh            # from the repo root; needs `claude` for the agents
#
# The real ledger, real hypotheses and real results are never touched: LAB_*_DIR point into demo/.
# The finished sandbox export is copied into results/demo/ (the dashboard's separate demo subtree).
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd -P)"
cd "$REPO"
SANDBOX="$REPO/demo/sandbox"
export LAB_DATA_DIR="$REPO/demo/data" LAB_HYPOTHESES_DIR="$SANDBOX/hypotheses"
export LAB_LEDGER_DIR="$SANDBOX/ledger" LAB_RESULTS_DIR="$SANDBOX/results"
export LOOP_AGENT_MODEL="${LOOP_AGENT_MODEL:-sonnet}"
TOOLS="uv run python $REPO/scripts/loop_tools.py"
LOG_DIR="$REPO/logs/demo-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$LOG_DIR"
IDS=(H-0001 H-0002 H-0003 H-0004)
NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

uv run python scripts/build_demo_world.py
rm -rf "$SANDBOX/ledger/returns" "$SANDBOX/results"; mkdir -p "$SANDBOX/ledger/returns" "$SANDBOX/results"
: > "$SANDBOX/ledger/trials.jsonl"

agent() { $TOOLS run-agent --agent "$1" --step "$2" --prompt-file "$3" --log-dir "$LOG_DIR" \
  --lab-root "$SANDBOX" "${@:4}"; }
spec_of() { $TOOLS spec-files "$1" | python3 -c \
  'import json,sys; [print(f["spec"], f["signal"]) for f in json.load(sys.stdin)]'; }

CLEARED=()
for id in "${IDS[@]}"; do
  cat > "$LOG_DIR/prompt-skeptic-pre-$id.txt" <<PROMPT
Pre-run review of $id. Lab root: $SANDBOX. Append your review to $LAB_RESULTS_DIR/$id/review.md
(section title "Pre-run review", last line "Recommendation (pre-run): clear|block"). Time now: $NOW.
Spec and signal module (read both): $(spec_of "$id")
Earlier specs are in $LAB_HYPOTHESES_DIR. Repo code, tests and config are under $REPO (read-only for you).
Run: uv run lab leakage $id
Context: this demo runs on a simulated universe (scripts/build_demo_world.py), as the spec says.
PROMPT
  agent skeptic "02-skeptic-pre-$id" "$LOG_DIR/prompt-skeptic-pre-$id.txt" \
    --expect-glob 'results/*/review.md' \
    --allowed-tool 'Bash(uv run pytest:*)' --allowed-tool 'Bash(uv run lab leakage:*)'
  status="$($TOOLS review-status "$LAB_RESULTS_DIR/$id/review.md" pre)"
  echo "$id: skeptic pre-run recommendation: $status"
  [ "$status" = "clear" ] && CLEARED+=("$id")
done

# The specs were committed in the sandbox repo before any run (pre-registration).
for id in "${CLEARED[@]}"; do uv run lab run "$id"; done
for id in "${CLEARED[@]}"; do uv run lab judge "$id"; done   # after every run, so N is the same for all

for id in "${CLEARED[@]}"; do
  cat > "$LOG_DIR/prompt-skeptic-post-$id.txt" <<PROMPT
Post-run review of $id. Lab root: $SANDBOX. Read $LAB_RESULTS_DIR/$id/verdict.json and the trials
for $id in $LAB_LEDGER_DIR/trials.jsonl. Append your review to $LAB_RESULTS_DIR/$id/review.md
(section title "Post-run review", last line "Recommendation (post-run): clear|block"). Time now: $NOW.
Spec and signal module: $(spec_of "$id"). Repo code, tests and config are under $REPO (read-only).
Context: this demo runs on a simulated universe (scripts/build_demo_world.py), as the spec says.
PROMPT
  agent skeptic "06-skeptic-post-$id" "$LOG_DIR/prompt-skeptic-post-$id.txt" \
    --expect-glob 'results/*/review.md' \
    --allowed-tool 'Bash(uv run pytest:*)' --allowed-tool 'Bash(uv run lab leakage:*)'
done
for id in "${CLEARED[@]}"; do
  cat > "$LOG_DIR/prompt-report-$id.txt" <<PROMPT
Write the report for $id. Lab root: $SANDBOX. Sources: $(spec_of "$id" | cut -d' ' -f1) (spec), $LAB_RESULTS_DIR/$id/verdict.json,
$LAB_RESULTS_DIR/$id/review.md, $LAB_LEDGER_DIR/trials.jsonl. Write only $LAB_RESULTS_DIR/$id/report.md.
Context: this demo runs on a simulated universe (scripts/build_demo_world.py); say so in the report.
PROMPT
  agent report "08-report-$id" "$LOG_DIR/prompt-report-$id.txt" --expect-glob 'results/*/report.md'
done
uv run lab dashboard export >/dev/null   # sandbox env: writes $SANDBOX/results/index.json and detail files
rm -rf "$REPO/results/demo"; mkdir -p "$REPO/results/demo"
cp "$SANDBOX/results/index.json" "$REPO/results/demo/index.json"
for id in "${CLEARED[@]}"; do cp -R "$SANDBOX/results/$id" "$REPO/results/demo/$id"; done
echo "demo pipeline finished; logs in $LOG_DIR"
