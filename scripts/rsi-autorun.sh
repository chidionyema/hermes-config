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
#    The budget is ONE constant, used by both the timeout and the message it
#    prints. Until 2026-08-06 they were two literals: the call was raised to 900
#    while the log line still said "TIMED OUT at 180s", so the only record of the
#    failure would have reported the wrong wall.
# 2a. REBUILD THE RULER FROM RECORDED OUTCOMES BEFORE TUNING. build_rsi_evalset.py appears in no
#     plist and no cron entry, so the evalset froze on the day it was written and the tuner
#     optimises against a failure distribution that may no longer exist — the same defect that
#     made the 2026-06-21 ruler actively harmful, just on a slower clock.
#
#     It does NOT on its own unblock rc=2, and this comment must not claim otherwise. MEASURED
#     2026-08-08 against a freshly rebuilt ruler (821 rejected attempts): every case still scores
#     got == weight — train total 130.00, non-gameable headroom 0.00. The cause is structural,
#     not staleness: every case is a PRESENCE regex over the prompt text (`require:
#     ["re-?run", "run .{0,20}again", ...]`), so a prompt that already mentions the phrase is at
#     full marks whatever the executor actually did, and re-weighting from a fresher corpus moves
#     the weights (unfixed 54.21 -> 58.64) while leaving every got == weight. Expressing "does
#     this BETTER" needs graded or behavioural cases in build_rsi_evalset.py's case generation —
#     a ruler-design change, deliberately NOT made unilaterally here. Until then rc=2 is the
#     honest state and the alert below says so. The rebuild still earns its place: it keeps the
#     weights tracking the real failure mix, so any graded case added later takes effect on the
#     current corpus rather than the June one. Safe to run unattended — the builder refuses
#     (rc=2 no corpus/support, rc=3 VERIFY_PROMPT) and keeps every ruler it replaces under
#     meta/rsi_evalsets/history/, so a bad rebuild is reversible.
"$PY" "$HERMES_HOME/scripts/build_rsi_evalset.py" --prompt EXECUTE_PROMPT --apply >> "$LOG" 2>&1
ruler_rc=$?
echo "$(ts) build_rsi_evalset(EXECUTE_PROMPT) exit=$ruler_rc (0=rebuilt from recorded outcomes; 2=no corpus or below support floor, previous ruler kept)" >> "$LOG"

TUNE_BUDGET_S=900
TIMEOUT_BIN="$(command -v timeout || command -v gtimeout || true)"
if [ -n "$TIMEOUT_BIN" ]; then
  # 180s could not fit the work: rsi-orchestrator makes up to THREE sequential
  # LLM attempts to generate a prompt variant, and a single claude-cli call
  # routinely exceeds a minute. Measured 2026-08-06: exit=124 at exactly 180s,
  # every run, so no candidate has ever been staged. This job runs once a day at
  # 04:30 — a 15-minute ceiling still guarantees a hung model cannot wedge it.
  "$TIMEOUT_BIN" "$TUNE_BUDGET_S" "$PY" "$HERMES_HOME/scripts/rsi-orchestrator.py" --run-prompt-tune --prompt-var EXECUTE_PROMPT >> "$LOG" 2>&1
  rc=$?
else
  "$PY" "$HERMES_HOME/scripts/rsi-orchestrator.py" --run-prompt-tune --prompt-var EXECUTE_PROMPT >> "$LOG" 2>&1
  rc=$?
fi
echo "$(ts) prompt-tune(EXECUTE_PROMPT) exit=$rc (staged for approval if passed gate; 2=ruler exhausted; 3=prompt has no authority over recorded failures; 124=timed out)" >> "$LOG"
[ "$rc" -eq 124 ] && echo "$(ts) prompt-tune TIMED OUT at ${TUNE_BUDGET_S}s — no candidate staged this run" >> "$LOG"
# rc=2 is a STANDING condition, not a transient failure: the ruler has no quality
# headroom left, so the tuner declined to spend a strategist call. It will keep
# returning 2 every night until meta/rsi_evalsets/EXECUTE_PROMPT.jsonl is grounded in
# recorded task outcomes. Say so once per run rather than letting a silent nonzero read
# as "the model was slow again" — which is exactly how zero landed improvements looked
# like bad luck for the ~2 months this job has been running.
# The old text here said "BLOCKED until the evalset is outcome-grounded". That is now FALSE and
# would misdirect the next reader: the evalset IS outcome-grounded (824 recorded attempts, rebuilt
# above) and still scores full marks, because its cases are presence regexes over the prompt text.
[ "$rc" -eq 2 ] && echo "$(ts) prompt-tune DECLINED — ruler exhausted; no LLM spend. The rebuilt, outcome-grounded ruler is ALSO at 0.00 headroom: its cases test whether the prompt MENTIONS a demand, not how well it meets one, so any prompt matching the regexes is at full marks. Prompt tuning stays a no-op until build_rsi_evalset.py emits graded/behavioural cases." >> "$LOG"
# rc=3 is a DIFFERENT refusal from rc=2 and must not be collapsed into it. rc=2 says the
# ruler cannot express a better prompt; rc=3 says a better prompt would not matter — the
# recorded failures are 99.1% unreachable by prompt text. Tuning the evalset fixes rc=2
# and does nothing for rc=3. The ledger line names the lever that IS reachable.
[ "$rc" -eq 3 ] && {
  echo "$(ts) prompt-tune DECLINED — no authority; no LLM spend. The reachable share of recorded failures is below the floor." >> "$LOG"
  "$PY" "$HERMES_HOME/scripts/rsi_outcome_ledger.py" >> "$LOG" 2>&1
}

echo "$(ts) rsi-autorun done (prompt-tune rc=$rc)" >> "$LOG"

# 3. SURFACE THE OUTCOME. This script ended `exit 0` unconditionally, so launchd recorded
#    LastExitStatus=0 for every run and NO monitor could tell a month of success from a month of
#    rc=2 / rc=3 / rc=124. That is exactly how ~2 months of zero staged candidates stayed
#    invisible: the only evidence was a log line nobody reads.
#
#    Alert on the TRANSITION, not on the state. rc=2 is a standing condition — alerting nightly
#    would train the operator to ignore the channel, which is worse than silence. So notify only
#    when the outcome CHANGES (including recovery back to 0) and keep the log as the full record.
STATE_F="$HERMES_HOME/meta/.rsi_last_outcome_rc"
prev_rc="$(cat "$STATE_F" 2>/dev/null || echo none)"
if [ "$rc" != "$prev_rc" ]; then
  case "$rc" in
    0)   msg="✅ RSI recovered: a prompt candidate was staged for approval (was rc=$prev_rc)." ;;
    1)   msg="⚠️ RSI: all prompt-tune attempts failed to beat the baseline (was rc=$prev_rc). No candidate staged." ;;
    2)   msg="🧪 RSI declined: EXECUTE_PROMPT ruler exhausted — 0.00 non-gameable headroom, no LLM spend. Measured 2026-08-08: a REBUILT ruler is also at full marks, because every case is a presence regex over the prompt text. A nightly rebuild will NOT clear this; it needs graded/behavioural cases in build_rsi_evalset.py. Prompt tuning is a no-op until then (was rc=$prev_rc)." ;;
    3)   msg="🧪 RSI declined: no authority — the prompt-reachable share of recorded failures is below the floor. Tuning the ruler will NOT fix this (was rc=$prev_rc)." ;;
    124) msg="⏱️ RSI timed out at ${TUNE_BUDGET_S}s — the model route is hung or slow. No candidate staged (was rc=$prev_rc)." ;;
    *)   msg="❓ RSI exited rc=$rc, an outcome this wrapper does not classify (was rc=$prev_rc)." ;;
  esac
  "$PY" "$HERMES_HOME/scripts/estate_alert.py" "$msg" >> "$LOG" 2>&1
  echo "$(ts) outcome CHANGED $prev_rc -> $rc; operator alerted" >> "$LOG"
  printf '%s' "$rc" > "$STATE_F"
fi

# Propagate the real status so launchd's LastExitStatus and the launchd receipt stop reporting
# success for a run that achieved nothing.
exit "$rc"
