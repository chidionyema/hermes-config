#!/usr/bin/env bash
# probe-template.sh — The 6-property probe contract template.
#
# Copy this file, rename to <your-probe-name>.sh, fill in the 5 placeholder
# blocks. Drop into ~/.hermes/scripts/ and register with the cronjob tool.
#
# The contract: every probe MUST implement all 6 properties.
# A probe that violates the contract is itself a dropped ball.
#
# 1. Declared budget  → BUDGET_SECS in the header
# 2. Derived timeout  → timeout = BUDGET_SECS * 2 (enforced via `timeout` cmd)
# 3. Heartbeat        → writes ~/.hermes/state/<name>.heartbeat at start
# 4. State file       → writes ~/.hermes/state/<name>.json with last result
# 5. Silent when unchanged → diffs against last state; exit 0 no stdout on no-change
# 6. One alert on change  → emits to queue, never raw

set -euo pipefail

# ─── PROBE IDENTITY ─────────────────────────────────────────────
NAME="${PROBE_NAME:-my-probe}"            # rename per probe
BUDGET_SECS="${BUDGET_SECS:-30}"          # declare expected duration
DERIVED_TIMEOUT=$(( BUDGET_SECS * 2 ))    # property 2
STATE_DIR="${HOME}/.hermes/state"
STATE_FILE="${STATE_DIR}/${NAME}.json"
HEARTBEAT_FILE="${STATE_DIR}/${NAME}.heartbeat"
QUEUE_SUBMIT="${HOME}/.hermes/scripts/hermes_queue.py"

mkdir -p "$STATE_DIR"

# ─── HEARTBEAT (property 3) ─────────────────────────────────────
# Write the heartbeat FIRST so a stuck probe is detectable.
date -u +"%Y-%m-%dT%H:%M:%SZ" > "$HEARTBEAT_FILE"

# ─── STATE LOAD (property 4) ────────────────────────────────────
last_status="unknown"
last_signature=""
if [[ -f "$STATE_FILE" ]]; then
  last_status=$(jq -r '.status // "unknown"' "$STATE_FILE" 2>/dev/null || echo "unknown")
  last_signature=$(jq -r '.signature // ""' "$STATE_FILE" 2>/dev/null || echo "")
fi

# ─── WORK (replace this block) ──────────────────────────────────
# Run your actual check here. Enforce the derived timeout.
# Capture exit code + a signature string + a message into the variables below.
# Example skeleton:
#
#   current_signature=$(some_command 2>&1 | sha256sum | cut -c1-16) || current_signature="ERROR"
#   current_status="pass"   # or "fail" or "degraded"
#   current_message="what the probe found (one line)"
#
current_signature="REPLACE_ME"
current_status="pass"
current_message="probe ran clean"

# ─── DIFF (property 5: silent when unchanged) ───────────────────
if [[ "$current_status" == "$last_status" && "$current_signature" == "$last_signature" ]]; then
  # Refresh heartbeat, write same state, exit silent
  date -u +"%Y-%m-%dT%H:%M:%SZ" > "$HEARTBEAT_FILE"
  exit 0
fi

# ─── STATE WRITE (property 4) ───────────────────────────────────
cat > "$STATE_FILE" <<EOF
{
  "name": "$NAME",
  "status": "$current_status",
  "signature": "$current_signature",
  "message": "$current_message",
  "budget_secs": $BUDGET_SECS,
  "derived_timeout_secs": $DERIVED_TIMEOUT,
  "checked_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
}
EOF

# ─── QUEUE SUBMIT (property 6: one alert on change) ─────────────
# Never echo to stdout — the queue is the dispatcher. Use hermes_queue.py
# to canonicalize and dedup. If a fingerprint already exists in the queue
# it will be coalesced, not duplicated.
if [[ -x "$QUEUE_SUBMIT" ]]; then
  "$QUEUE_SUBMIT" submit \
    --source "$NAME" \
    --severity "$current_status" \
    --message "$current_message" \
    --fingerprint "$(echo -n "$current_signature" | sha256sum | cut -c1-16)" \
    || true
fi

# Refuse to print directly — the queue is the only allowed channel.
# If you are tempted to add `echo "$current_message"` here, that is a
# regression to raw-alert delivery. The dropped-ball watchdog will catch it.
exit 0
