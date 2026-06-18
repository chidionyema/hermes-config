#!/bin/bash
# idle-learning-probe — fires (exit 2) when idle-continuous-learning has exited
# non-zero MORE THAN ONCE in the last 24h. Reads the run-log the pipeline appends
# on every run. This is the per-cron health probe required by Ball 16, and it is
# registered as a watched claim in the dropped-ball ledger so the watchdog re-runs
# it every audit cycle. Escalates to the relay queue on failure.
set -u
LOG="$HOME/.hermes/logs/maintenance/idle-learning-runs.jsonl"
Q="$HOME/.hermes/scripts/hermes_queue.py"

if [ ! -f "$LOG" ]; then
  echo "idle-learning-probe: no run-log yet — PASS (no runs to judge)"
  exit 0
fi

FAILS=$(python3 - "$LOG" <<'PY'
import json, sys, time
from datetime import datetime, timezone
cut = time.time() - 86400
n = 0
for line in open(sys.argv[1]):
    line = line.strip()
    if not line:
        continue
    try:
        o = json.loads(line)
        ts = datetime.strptime(o["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        continue
    if ts >= cut and int(o.get("exit", 0)) != 0:
        n += 1
print(n)
PY
)
FAILS=${FAILS:-0}
echo "idle-learning-probe: ${FAILS} failed run(s) in last 24h (threshold > 1)"
if [ "$FAILS" -gt 1 ]; then
  python3 "$Q" submit --source idle-learning-health --severity crit \
    --message "idle-continuous-learning failed ${FAILS} times in 24h — recurring, investigate root cause" \
    >/dev/null 2>&1 || true
  echo "PROBE: FAIL — idle-continuous-learning is failing repeatedly"
  exit 2
fi
echo "PROBE: PASS"
exit 0
