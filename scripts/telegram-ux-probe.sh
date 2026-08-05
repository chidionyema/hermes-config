#!/bin/bash
# telegram-ux-probe.sh — shell wrapper around telegram_ux_probe.py.
#
# Replaces goal-of-the-moment.sh: instead of asking "what's the goal?" every
# hour, this watchdog actually probes Telegram UX state and only delivers
# to the user when something has changed or something is broken.
#
# Output policy (via Python exit code):
#   0 + empty stdout  →  silent (healthy AND unchanged)
#   0 + non-empty stdout  →  deliver verbatim as a Telegram message
#   non-zero exit  →  alert (probe crashed)
#
# Cron schedule: 06:00 daily.

set -u

PROBE="$HOME/.hermes/scripts/telegram_ux_probe.py"

if [ ! -f "$PROBE" ]; then
  echo "Telegram UX probe missing: $PROBE" >&2
  exit 1
fi

# Hard-timeout the probe so a wedged gateway can't hang the cron.
output=$(timeout 30 python3 "$PROBE" 2>&1)
rc=$?

if [ "$rc" -ne 0 ]; then
  echo "Telegram UX probe crashed (exit=$rc)"
  echo "$output"
  exit 1
fi

# Empty stdout = silent (healthy, unchanged).
if [ -z "$output" ]; then
  exit 0
fi

# Deliver to Telegram, hard-timed.
timeout 15 hermes send --to telegram "🔔 *Telegram UX probe*

$output" 2>&1
rc=$?
exit $rc
