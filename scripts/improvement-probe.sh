#!/bin/bash
# Self-improvement probe: finds common gaps and files structured failure entries
# Runs every 6h via cron. Generates training data for the self-regression corpus.
set -e
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
CORPUS="$HERMES_HOME/logs/self-regression-corpus.json"
PROBE_LOG="$HERMES_HOME/logs/maintenance/probe-findings.jsonl"
mkdir -p "$(dirname "$PROBE_LOG")"

# Load existing corpus
ENTRIES=$(python3 -c "
import json
try:
    with open('$CORPUS') as f:
        data = json.load(f)
    print(len(data))
except: print(0)
" 2>/dev/null)

FOUND=0

# Probe 1: Check for stale .gitignore
if [ -f "$HERMES_HOME/.gitignore" ]; then
    if grep -q ".agent/" "$HERMES_HOME/.gitignore" 2>/dev/null; then
        echo "  # 1: .gitignore clean"
    else
        echo "  ⚠️  .gitignore may be missing .agent/ entries"
    fi
fi

# Probe 2: Check for uncommitted changes >24h
DIRTY_COUNT=$(cd "$HERMES_HOME" && git status --porcelain 2>/dev/null | wc -l)
if [ "$DIRTY_COUNT" -gt 0 ]; then
    echo "  ⚠️  $DIRTY_COUNT uncommitted files"
fi

# Probe 3: Check gateway health
if curl -sf http://localhost:9090/health >/dev/null 2>&1; then
    :  # healthy
else
    echo "  ⚠️  Gateway not responding"
    echo '{"source":"probe","domain":"infra/monitoring","trigger":"Gateway health check failed","fix":"Restart gateway: launchctl start io.hermes.gateway","test":"Would policy now detect gateway failures?","added_at":"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"}' >> "$PROBE_LOG"
    FOUND=$((FOUND+1))
fi

# Probe 4: Check cron scheduler health
if [ -f "$HERMES_HOME/cron/jobs.json" ]; then
    STALE=$(python3 -c "
import json, time
with open('$HERMES_HOME/cron/jobs.json') as f:
    jobs = json.load(f).get('jobs', [])
now = time.time()
stale = 0
for j in jobs:
    last = j.get('last_run_at')
    if last:
        try:
            from datetime import datetime
            lt = datetime.fromisoformat(last)
            if (now - lt.timestamp()) > 86400:
                stale += 1
        except: pass
print(stale)
" 2>/dev/null)
    if [ "$STALE" -gt 0 ] && [ "$STALE" -gt 0 ] 2>/dev/null; then
        echo "  ⚠️  $STALE cron jobs not run in 24h+"
    fi
fi

# Probe 5: Check for duplicate/similar policies
DUPLICATE=$(python3 -c "
import json, os, itertools
from difflib import SequenceMatcher
pdir = '$HERMES_HOME/policies'
policies = []
for fname in sorted(os.listdir(pdir)):
    if fname.endswith('.json'):
        with open(os.path.join(pdir, fname)) as f:
            p = json.load(f)
        policies.append(p)
for a, b in itertools.combinations(policies, 2):
    r = SequenceMatcher(None, a.get('trigger',''), b.get('trigger','')).ratio()
    if r > 0.7:
        print(f'{a["id"]} ~ {b["id"]} (similarity={r:.2f})')
" 2>/dev/null)
if [ -n "$DUPLICATE" ]; then
    echo "  ⚠️  Similar policy pairs:"
    echo "$DUPLICATE" | while read line; do echo "       $line"; done
fi

echo "--- probe complete: $FOUND findings logged ---"
