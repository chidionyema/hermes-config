#!/bin/bash
# uncommitted-watch.sh — silent watchdog for uncommitted work.
# Run by cron every 6h. Silent unless >10 uncommitted files.
# No-agent mode: stdout IS the message.

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
REPOS=(
    "$HERMES_HOME"
    "$HOME/prospector"
    "$HOME/lux"
    "$HOME/signal-engine"
)

total=0
report=""

for repo in "${REPOS[@]}"; do
    if [ ! -d "$repo/.git" ]; then
        continue
    fi
    count=$(cd "$repo" && git status --short 2>/dev/null | wc -l | tr -d ' ')
    if [ "$count" -gt 0 ]; then
        total=$((total + count))
        report="$report\n  $repo: $count uncommitted files"
    fi
done

if [ "$total" -gt 10 ]; then
    echo "⚠️  $total uncommitted files across repos:$report"
elif [ "$total" -gt 0 ]; then
    echo "📁 $total uncommitted file(s) — below threshold, no action needed."
else
    # Silent — nothing to report
    exit 0
fi
