#!/bin/bash
# memory-capacity-probe — substrate prevention for the "memory tool fails to add" wall.
# ROOT CAUSE (not a tool bug): memory_tool.py add() hard-rejects when an entry would
# push a file past its char cap (user=1375, memory=2200 in config.yaml). The wall was
# only discovered AT failure time, with no headroom to add the new rule. This probe
# fires at 85% of cap so the file gets consolidated BEFORE it blocks a write — turning
# a surprise failure into an early, actionable warning. Escalates via the relay queue.
set -u
CFG="$HOME/.hermes/config.yaml"
MEMDIR="$HOME/.hermes/memories"
Q="$HOME/.hermes/scripts/hermes_queue.py"
THRESH=85

cap() { grep -E "^[[:space:]]*$1:" "$CFG" | head -1 | grep -oE '[0-9]+'; }
ULIM=$(cap user_char_limit);   ULIM=${ULIM:-1375}
MLIM=$(cap memory_char_limit); MLIM=${MLIM:-2200}

chars() { [ -f "$1" ] && python3 -c "import sys;print(len(open(sys.argv[1]).read().strip()))" "$1" || echo 0; }
UC=$(chars "$MEMDIR/USER.md")
MC=$(chars "$MEMDIR/MEMORY.md")

fail=0
check() { # name chars limit
  local name="$1" c="$2" lim="$3"
  local pct=$(( c * 100 / lim ))
  printf '  %-10s %4d/%-4d chars  (%d%%)\n' "$name" "$c" "$lim" "$pct"
  if [ "$pct" -ge "$THRESH" ]; then
    echo "  ❗ $name at ${pct}% of cap — consolidate now (replace/merge entries) before it blocks a write."
    python3 "$Q" submit --source memory-capacity --severity warn \
      --message "$name memory at ${pct}% of ${lim}-char cap; consolidate before it blocks writes" \
      >/dev/null 2>&1 || true
    fail=1
  fi
}

echo "memory-capacity-probe (warn at ${THRESH}% of cap):"
check USER.md "$UC" "$ULIM"
check MEMORY.md "$MC" "$MLIM"
echo "---"
if [ "$fail" = 0 ]; then
  echo "PROBE: PASS — all memory files have headroom (< ${THRESH}% of cap)."
  exit 0
else
  echo "PROBE: FAIL — a memory file is near its cap; consolidate (this is the early warning, not the wall)."
  exit 2
fi
