#!/bin/bash
# goal-ping-template.sh
# Reusable template for a user-facing cron-no-agent Telegram ping.
# Copy to ~/.hermes/scripts/<your-ping-name>.sh, edit the MESSAGE,
# chmod +x, test standalone, then attach via:
#   cronjob create --no-agent --schedule "every Nm" --script <name>.sh
#
# Working pattern (the `--quiet` / `>/dev/null` variants HANGS in cron
# context — see SKILL.md "Sub-pitfall — hermes send --quiet HANGS").
set -u

MESSAGE="${1:-Otto here — what's the goal of the moment?}"

# Capture stdout (do NOT redirect to /dev/null — triggers the cron hang).
output=$(hermes send --to telegram "$MESSAGE" 2>&1)
rc=$?

# Echo the result so the script exits cleanly (avoids pipe-block on CLI teardown).
echo "$output"

if [ "$rc" -ne 0 ]; then
  echo "DELIVERY FAILED (hermes send exit=$rc)" >&2
  exit 1
fi
exit 0
