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

# Bare `python3` is the launchd/cron PATH trap: the scheduler's PATH is not a login
# shell's, so resolve an interpreter explicitly and fall back rather than exit 127.
PY="$(command -v python3 || true)"
[ -x "$PY" ] || PY=/usr/local/bin/python3
[ -x "$PY" ] || PY=/usr/bin/python3

# Wait for DNS before probing. This job runs at 06:00 and failed with
#   httpx.ConnectError: [Errno 8] nodename nor servname provided, or not known
# — a resolver that was not up yet, not a Telegram fault. A cron entry does not retry,
# so the first attempt is the only attempt and the whole day's probe was lost to a
# transient. Same failure shape and same fix as scripts/backup_store.py's
# _wait_for_endpoint, which is what turned that job's nine-night outage into a PASS.
for attempt in 1 2 3 4 5 6; do
  if ping -c1 -t2 api.telegram.org >/dev/null 2>&1 \
     || "$PY" -c "import socket,sys; socket.getaddrinfo('api.telegram.org',443)" 2>/dev/null; then
    break
  fi
  # Deliberately NOT exit 0. This capability is scored requires=exit0, so a clean exit
  # here would record a met receipt for a probe that never ran — the exact
  # "exit-0-did-nothing" laundering the receipt layer exists to catch. A non-zero exit
  # states the true thing: no probe happened, and the reason was the network.
  [ "$attempt" = 6 ] && { echo "Telegram UX probe did not run: api.telegram.org did not resolve after ~60s. This is a network failure, not a Telegram UX failure; the next scheduled run retries." >&2; exit 1; }
  sleep $((attempt * 3))
done

# Hard-timeout the probe so a wedged gateway can't hang the cron.
output=$(timeout 30 "$PY" "$PROBE" 2>&1)
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
