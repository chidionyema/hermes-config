#!/bin/bash
# Reliability watchdog — the job that turns silence into a failure.
#
# The 2026-08-05 audit found seven capabilities dark and ten latches held past their
# window, none of which had ever raised an alert, because every existing watchdog
# watched for FAILURES and none of these had failed. They had gone quiet, and quiet
# was indistinguishable from healthy.
#
# This runs both probes and exits non-zero when the estate cannot prove it is working.
# A non-zero exit is what makes it visible to the cron layer as a real failure.
#
# Latch release runs with --apply: only latches declared auto_release in
# capabilities.json move, and ESTATE_PAUSED is deliberately not one of them.

set -uo pipefail
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
PY="$(command -v python3)"
OUT="$HERMES_HOME/state/reliability_status.json"

cap_out="$("$PY" "$HERMES_HOME/scripts/capability_audit.py" 2>&1)"; cap_rc=$?
latch_out="$("$PY" "$HERMES_HOME/scripts/latch_expiry.py" --apply 2>&1)"; latch_rc=$?

echo "$cap_out"
echo
echo "$latch_out"

# Machine-readable status so the morning brief and estate probe read one source of truth
# rather than each re-deriving health from whatever signal is nearest.
#
# Deliberately NOT gated on the audit's exit code: --json exits 1 whenever something is
# dark, so `&& mv` would publish a status file only while the estate was healthy and go
# stale exactly when it mattered. Gate on the file being non-empty instead.
"$PY" "$HERMES_HOME/scripts/capability_audit.py" --json > "$OUT.tmp" 2>/dev/null
if [ -s "$OUT.tmp" ]; then mv "$OUT.tmp" "$OUT"; else rm -f "$OUT.tmp"; fi

if [ "$cap_rc" -ne 0 ] || [ "$latch_rc" -ne 0 ]; then
  echo
  echo "RELIABILITY: NOT PROVEN (capabilities rc=$cap_rc, latches rc=$latch_rc)"
  exit 1
fi
echo
echo "RELIABILITY: every capability proven producing, no latch past its window"
exit 0
