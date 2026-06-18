#!/bin/bash
# queue-curate — Otto's curation pass over the relay queue (FIRE 0 consumer).
# Drains incoming events, then writes a STRUCTURED digest of currently-open issues
# to queue/pending-digest.json for the otto-dispatch relay step to triage.
#
# BALL 17 FIX: the curator NO LONGER delivers to the user. The correct topology is
#   cron -> queue -> queue-curate (writes file) -> otto-dispatch (Otto triage) -> user
# Previously deliver:origin sent this digest straight to the user's Telegram, bypassing
# Otto-as-dispatcher. This script now stays SILENT on stdout (cron deliver:local writes
# nothing to anyone); the pending-digest.json file is the only channel, read by
# otto-dispatch.py on the next dispatch tick.
set -u
Q="$HOME/.hermes/scripts/hermes_queue.py"
DIGEST="$HOME/.hermes/queue/pending-digest.json"

python3 "$Q" drain >/dev/null 2>&1 || true
STATUS_FILE=$(mktemp)
python3 "$Q" status >"$STATUS_FILE" 2>/dev/null || printf '{}' >"$STATUS_FILE"

# Always (re)write the pending digest — items:[] when healthy. Atomic via rename.
# NOTE: the queue STATUS is passed by file (argv), NOT stdin — `python3 -` reads its
# program from stdin (the heredoc), so stdin is unavailable for data here.
python3 - "$DIGEST" "$STATUS_FILE" <<'PY' 2>/dev/null || true
import json, os, sys
from datetime import datetime, timezone
digest, status_file = sys.argv[1], sys.argv[2]
try:
    d = json.load(open(status_file))
except Exception:
    d = {"open_fingerprints": 0, "items": []}
items = sorted(d.get("items", []), key=lambda x: (x.get("severity") != "crit", -x.get("count", 0)))
out = {
    "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "open_fingerprints": d.get("open_fingerprints", len(items)),
    "items": [
        {"severity": i.get("severity", "warn"), "count": i.get("count", 1),
         "source": i.get("source", "?"), "fingerprint": i.get("fingerprint", "")}
        for i in items
    ],
}
os.makedirs(os.path.dirname(digest), exist_ok=True)
tmp = digest + ".tmp"
with open(tmp, "w") as f:
    json.dump(out, f, indent=2)
os.replace(tmp, digest)
PY
rm -f "$STATUS_FILE"
exit 0
