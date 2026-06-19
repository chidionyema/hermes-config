#!/bin/bash
# goal-of-the-moment.sh
# Cron ping: send a Telegram message in Otto's voice asking for the goal of the moment.
#
# Runs under `hermes cron --no-agent` — script stdout is delivered verbatim.
# Exit codes: 0 delivered, non-zero = alert (broken watchdog).
#
# NOTE: Do NOT use `hermes send --quiet` — that flag currently causes the CLI
# to hang (timeout 124) instead of exiting. Capture stdout to /dev/null
# without the flag instead.
set -u

# Run hermes send, capture its full output (it prints "Sent to ..." on success).
output=$(hermes send --to telegram "Otto here — what's the goal of the moment?" 2>&1)
rc=$?

# Echo the captured output so the cron scheduler can deliver it (or capture it
# in output/ for diagnostics). The scheduler is configured with deliver=origin
# so the message already reached the user via Telegram; stdout here is logged.
echo "$output"

if [ "$rc" -ne 0 ]; then
  echo "DELIVERY FAILED (hermes send exit=$rc)" >&2
  exit 1
fi
exit 0
