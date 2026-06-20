#!/usr/bin/env bash
# rsi-autorun.sh — fenced, autonomous RSI self-improvement tick (cron-driven).
#
# Fence (do NOT weaken):
#   • OFF_SWITCH must be ARMED (file present) or this no-ops.
#   • Prompt tuning only STAGES a candidate for human approval (Double-Key Lock
#     via Telegram) — it never auto-merges. VERIFY_PROMPT is deliberately NOT
#     auto-tuned here (changing the verifier prompt could weaken the proof gate);
#     tune it only via an explicit human-initiated run.
#   • Money/identity/contract/code self-mods never run from this job.
#
# Each run: (1) re-verify + re-sign the evidence ledger, (2) attempt one fenced
# EXECUTE_PROMPT tune that must clear the held-out improvement gate to be staged.
set -u
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
PY=/usr/local/bin/python3
LOG="$HERMES_HOME/logs/rsi-autorun.log"
mkdir -p "$(dirname "$LOG")"
ts() { date "+%Y-%m-%dT%H:%M:%S%z"; }

if [ ! -f "$HERMES_HOME/meta/OFF_SWITCH" ]; then
  echo "$(ts) OFF_SWITCH absent — self-improvement disarmed, skipping." >> "$LOG"
  exit 0
fi

echo "$(ts) rsi-autorun start" >> "$LOG"

# 1. Keep the evidence ledger independently re-verified (signs/un-signs by truth).
"$PY" "$HERMES_HOME/scripts/evidence_verify.py" >> "$LOG" 2>&1
echo "$(ts) evidence_verify exit=$?" >> "$LOG"

# 2. Fenced prompt tune — stages for human approval only. Needs the LLM route;
#    if the model is unavailable/slow the run returns non-zero (or is timed out)
#    and we simply log it — a hung model must never wedge the job.
TIMEOUT_BIN="$(command -v timeout || command -v gtimeout || true)"
if [ -n "$TIMEOUT_BIN" ]; then
  "$TIMEOUT_BIN" 180 "$PY" "$HERMES_HOME/scripts/rsi-orchestrator.py" --run-prompt-tune --prompt-var EXECUTE_PROMPT >> "$LOG" 2>&1
else
  "$PY" "$HERMES_HOME/scripts/rsi-orchestrator.py" --run-prompt-tune --prompt-var EXECUTE_PROMPT >> "$LOG" 2>&1
fi
echo "$(ts) prompt-tune(EXECUTE_PROMPT) exit=$? (staged for approval if passed gate; 124=timed out)" >> "$LOG"

echo "$(ts) rsi-autorun done" >> "$LOG"
exit 0
