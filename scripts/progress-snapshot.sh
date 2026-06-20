#!/usr/bin/env bash
# progress-snapshot.sh — decoupled autonomy-trend snapshot (cron-driven).
#
# progress.snapshot() also runs inside coordinator.tick(), but that stops if the
# daemon stops. This job makes the trend hang-proof: it accrues even when the
# coordinator is down. snapshot() self-throttles (~50min) so hourly is safe.
set -u
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
PY=/usr/local/bin/python3
LOG="$HERMES_HOME/logs/progress-snapshot.log"
mkdir -p "$(dirname "$LOG")"

"$PY" - <<'PYEOF' >> "$LOG" 2>&1
import os, sys, time
sys.path.insert(0, os.path.expanduser("~/.hermes/scripts"))
try:
    import coordinator as C
    import progress as P
    conn = C.connect()
    try:
        P.snapshot(conn)
        print(time.strftime("%Y-%m-%dT%H:%M:%S"), "progress snapshot ok")
    finally:
        conn.close()
except Exception as e:
    print(time.strftime("%Y-%m-%dT%H:%M:%S"), "progress snapshot error:", e)
PYEOF
exit 0
