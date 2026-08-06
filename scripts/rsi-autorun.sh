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

# Canonical: OFF_SWITCH present = ARMED (see scripts/learning_switch.py).
if [ ! -f "$HERMES_HOME/meta/OFF_SWITCH" ]; then
  echo "$(ts) OFF_SWITCH absent — self-improvement DISARMED, skipping." >> "$LOG"
  exit 0
fi

echo "$(ts) rsi-autorun start" >> "$LOG"

# 1. Keep the evidence ledger independently re-verified (signs/un-signs by truth).
# Capture rc IMMEDIATELY. `echo "$(ts) ... exit=$?"` expands $(ts) first, so $?
# reports date(1)'s status — always 0. Both lines below logged exit=0 for every
# run since this file was written, including the 2026-08-06 14:42 run whose
# prompt-tune sat at exactly 180s (the timeout boundary) and still read as clean.
"$PY" "$HERMES_HOME/scripts/evidence_verify.py" >> "$LOG" 2>&1
rc=$?
echo "$(ts) evidence_verify exit=$rc" >> "$LOG"

# 2. Fenced prompt tune — stages for human approval only. Needs the LLM route;
#    if the model is unavailable/slow the run returns non-zero (or is timed out)
#    and we simply log it — a hung model must never wedge the job.
TIMEOUT_BIN="$(command -v timeout || command -v gtimeout || true)"
if [ -n "$TIMEOUT_BIN" ]; then
  # 180s could not fit the work: rsi-orchestrator makes up to THREE sequential
  # LLM attempts to generate a prompt variant, and a single claude-cli call
  # routinely exceeds a minute. Measured 2026-08-06: exit=124 at exactly 180s,
  # every run, so no candidate has ever been staged. This job runs once a day at
  # 04:30 — a 15-minute ceiling still guarantees a hung model cannot wedge it.
  "$TIMEOUT_BIN" 900 "$PY" "$HERMES_HOME/scripts/rsi-orchestrator.py" --run-prompt-tune --prompt-var EXECUTE_PROMPT >> "$LOG" 2>&1
  rc=$?
else
  "$PY" "$HERMES_HOME/scripts/rsi-orchestrator.py" --run-prompt-tune --prompt-var EXECUTE_PROMPT >> "$LOG" 2>&1
  rc=$?
fi
echo "$(ts) prompt-tune(EXECUTE_PROMPT) exit=$rc (staged for approval if passed gate; 124=timed out)" >> "$LOG"
[ "$rc" -eq 124 ] && echo "$(ts) prompt-tune TIMED OUT at 180s — no candidate staged this run" >> "$LOG"

echo "$(ts) rsi-autorun done" >> "$LOG"
exit 0
