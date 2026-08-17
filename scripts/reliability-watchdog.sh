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
# Code dir and data dir are separate: the probes always come from beside THIS script,
# while HERMES_HOME selects which estate they read. Conflating the two meant pointing
# the watchdog at a fixture estate also made it look for the probes there, so the
# fixture run failed on ENOENT and read as "unhealthy" — a green test for a red reason.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
PY="$(command -v python3)"
OUT="$HERMES_HOME/state/reliability_status.json"

# Latch release first — it MUTATES state (only latches declared auto_release move),
# so the report below observes the estate as this run leaves it, not as it found it.
"$PY" "$SCRIPT_DIR/latch_expiry.py" --apply >/dev/null 2>&1 || true

# Then REPAIR, in the same slot and for the same reason. Detection was never the gap: on
# 2026-08-17 eight of twenty-one estate agents were unloaded, all of them registered, all
# of them correctly DARK — and nothing put them back. alarm_gate.py fires on state CHANGE,
# so each one alarmed once and went quiet; an unloaded job cannot alarm about itself twice.
# launchd_selfheal.py re-bootstraps any estate agent that is unloaded and NOT declared
# retired by a Disabled key in its own plist, and REFUSES a label it has already healed
# more than 4 times in 24h — because healing a crash-loop every hour would make it look
# healthy. A refusal leaves the agent down, so the capability stays DARK and the report
# below alarms on it, which is the intended path.
"$PY" "$SCRIPT_DIR/launchd_selfheal.py" --apply >> "$HERMES_HOME/state/launchd_selfheal.log" 2>&1 || true

# Everything else — capability audit, latches, missed runs, the alarm gate, and the
# status file at $OUT — is composed by reliability_report.py, which owns both what
# counts as a fault and whether the founder has already been told about it.
#
# "Healthy = say nothing" was necessary but NOT sufficient. cron/scheduler.py:1409-1412:
# "non-zero exit / timeout -> delivered as an error alert". The exit CODE alone triggers
# delivery, so the previous version of this script — which exited 1 for as long as
# anything was dark — would have Telegrammed the founder every hour indefinitely. On the
# first audit that was 17 rows, 11 of them false (receipt instrumentation was younger
# than those jobs' periods). An alarm that is mostly wrong and always repeating is one
# that gets muted, which is exactly how otto-dispatch sat disabled for 46 days. Repeats
# are now suppressed by state fingerprint; see alarm_gate.py.
exec "$PY" "$SCRIPT_DIR/reliability_report.py"
