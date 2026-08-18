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
for attempt in 1 2 3 4; do
  if ping -c1 -t2 api.telegram.org >/dev/null 2>&1 \
     || "$PY" -c "import socket,sys; socket.getaddrinfo('api.telegram.org',443)" 2>/dev/null; then
    break
  fi
  # Deliberately NOT exit 0. This capability is scored requires=exit0, so a clean exit
  # here would record a met receipt for a probe that never ran — the exact
  # "exit-0-did-nothing" laundering the receipt layer exists to catch. A non-zero exit
  # states the true thing: no probe happened, and the reason was the network.
  # 4 attempts (sleeps 3+6+9 = 18s), not 6 (45s): the whole script must finish inside the
  # scheduler's cap, _DEFAULT_SCRIPT_TIMEOUT = 120 at cron/scheduler.py:855, and config.yaml
  # sets no cron.script_timeout_seconds override. Worst case is 18 (DNS) + 45 (probe)
  # + 45 (send) = 108s, 12s under the cap. The old 6-attempt loop plus the 45s send guard
  # would total 120s exactly and trip scheduler.py:1188 ("Script timed out after Ns").
  [ "$attempt" = 4 ] && { echo "Telegram UX probe did not run: api.telegram.org did not resolve after ~18s. This is a network failure, not a Telegram UX failure; the next scheduled run retries." >&2; exit 1; }
  sleep $((attempt * 3))
done

# Hard-timeout the probe so a wedged gateway can't hang the cron.
# 45, not 30. The 2026-08-18 06:00 run died on rc=124 at 30s. The probe renders 10 panels in a
# FRESH process, so it pays every cold import; `run` alone costs 4.4-12.6s because
# cockpit.render_run -> estate._load_coordinator imports coordinator.py -> route.py -> the whole
# openai SDK (825 modules, 14.3s of the 17.4s profile). Measured wall time on a warm host is
# 11.4-20.6s over three runs, so 30 was only 1.5x the worst case and 06:00 runs against other
# cron jobs on the same CPU. 45 is 2.2x the worst measurement and still fits the 120s cap above.
output=$(timeout 45 "$PY" "$PROBE" 2>&1)
rc=$?

if [ "$rc" -ne 0 ]; then
  # Say which failure it was. A timeout and a traceback need different fixes, and calling both
  # "crashed" is what sent the 06:00 alert looking for a bug in the probe instead of the clock.
  if [ "$rc" -eq 124 ]; then
    echo "Telegram UX probe TIMED OUT after 45s (rc=124). The panels got slower; re-measure before raising this again — the ceiling is the 120s scheduler cap."
  else
    echo "Telegram UX probe crashed (exit=$rc)"
  fi
  echo "$output"
  exit 1
fi

# Empty stdout = silent (healthy, unchanged).
if [ -z "$output" ]; then
  exit 0
fi

# Deliver to Telegram, hard-timed. 45 > 30 ON PURPOSE: the transport underneath sets its own
# 30s HTTP client timeout (tools/send_message_tool.py:1359,1384 aiohttp.ClientTimeout(total=30);
# gateway/platforms/telegram.py httpx timeout=30.0). The old `timeout 15` sat BELOW that, so a
# slow-but-recoverable POST was SIGTERMed mid-flight at 15s with rc=124 and the client's own
# error handling never ran. An outer guard above the inner one lets the transport fail cleanly
# and only fires if the transport itself wedges. Back to 45 from 60: the probe guard above went
# 30 -> 45 and the three guards have to sum under the 120s cap. 45 is already 1.5x the inner 30s
# client timeout, so the transport still gets to fail on its own terms first.
delivery=$(timeout 45 hermes send --to telegram "🔔 *Telegram UX probe*

$output" 2>&1)
rc=$?

if [ "$rc" -ne 0 ]; then
  # Un-commit the digest. telegram_ux_probe.py:121 writes it BEFORE this delivery is attempted,
  # so leaving it in place makes the next run see prev == digest (telegram_ux_probe.py:117) and
  # exit silent — the undelivered report would be lost forever and could never self-retry.
  rm -f "$HOME/.hermes/cache/telegram-ux-probe.digest"
  # Keep the undelivered report in the scheduler receipt (_write_receipt, scheduler.py:1089).
  echo "Telegram UX probe: DELIVERY FAILED (timeout/exit=$rc). Digest reset; next run retries."
  echo "$delivery"
  echo "--- undelivered report ---"
  echo "$output"
  # Never propagate a bare 124 — indistinguishable from a probe crash upstream.
  exit 1
fi

echo "$delivery"
exit 0
