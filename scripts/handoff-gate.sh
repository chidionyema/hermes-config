#!/bin/bash
# handoff-gate.sh — Claude's pre-handoff integrity gate.
#
# I run this BEFORE telling the founder "done." If it fails, I do not hand off.
# It checks things unit tests can't: integration wiring, absence of stubs,
# fence integrity, and that the send-path actually delivers.
#
# Exit 0 = gate clear. Exit 1 = blocked — fix before claiming done.

set -euo pipefail

COCKPIT="$HOME/Documents/code/sentinel-loop"
HERMES="$HOME/.hermes"
FAIL=0
ok(){ printf '  ✅ %s\n' "$1"; }
bad(){ printf '  ❌ %s\n' "$1"; FAIL=1; }

echo "══════════════════════════════════════════════════════════════════"
echo "HANDOFF GATE — $(date '+%Y-%m-%d %H:%M')"
echo "All checks must pass before claiming any work item done."
echo "══════════════════════════════════════════════════════════════════"
echo ""

# ── 1. Enforcement tests (send-path integrity) ──────────────────────
echo "─ 1. Send-path enforcement"
cd "$COCKPIT"
if python3 -m pytest tests/cockpit/test_enforcement.py -q --tb=no 2>/dev/null; then
  ok "enforcement tests pass (nav bar sent, callbacks routed, no stubs)"
else
  bad "enforcement tests FAILED — a UI element is defined but never delivered"
fi
echo ""

# ── 2. No half-baked stub language in production code ───────────────
echo "─ 2. No half-baked stubs in production paths"
# Patterns that mean "this feature is not actually implemented"
# (excludes: the legitimate Claude fence text, section header comments,
#  and "placeholder" in the thinking-indicator which is a real feature)
STUB_MARKERS=(
  "coming soon"
  "not yet implemented"
  "full impl in"
  "handler registered.*full impl"
)
FILES_TO_CHECK=(
  "$COCKPIT/sentinel/cockpit/server.py"
  "$COCKPIT/sentinel/cockpit/menu.py"
)
FOUND=0
for marker in "${STUB_MARKERS[@]}"; do
  for f in "${FILES_TO_CHECK[@]}"; do
    MATCHES=$(grep -in "$marker" "$f" 2>/dev/null || true)
    if [ -n "$MATCHES" ]; then
      if [ $FOUND -eq 0 ]; then
        bad "half-baked stub language in production:"
        FOUND=1
      fi
      echo "$MATCHES" | while read line; do
        printf '    %s:%s\n' "$(basename "$f")" "$line"
      done
    fi
  done
done
if [ $FOUND -eq 0 ]; then
  ok "no half-baked stubs in production paths"
fi
echo ""

# ── 3. Callback routing completeness ────────────────────────────────
echo "─ 3. Callback routing completeness"
M="$COCKPIT/sentinel/cockpit/menu.py"
S="$COCKPIT/sentinel/cockpit/server.py"

# Extract callback prefixes from handle_callback in menu.py
# Look for patterns like: data.startswith("prefix:")
MENU_PREFIXES=$(grep -o 'data\.startswith("[^"]*")' "$M" 2>/dev/null | \
  sed 's/data\.startswith("//;s/")//' | grep -v '^d"$' | grep ':' | sort -u || true)

# Extract callback prefixes from server.py router
SERVER_PREFIXES=$(grep -o 'data\.startswith("[^"]*")' "$S" 2>/dev/null | \
  sed 's/data\.startswith("//;s/")//' | sort -u || true)

UNROUTED=""
for prefix in $MENU_PREFIXES; do
  # Skip prefixes handled by the d* catch-all pattern in server router
  # (server.py routes: data.startswith("d") && data[1] in "halgcdsxkirz")
  first_char=$(printf '%s' "$prefix" | cut -c1)
  if [ "$first_char" = "d" ] && [ ${#prefix} -le 3 ]; then continue; fi
  # Check if this prefix has an exact match in server router
  FOUND_IN_SERVER=0
  for sp in $SERVER_PREFIXES; do
    if [ "$prefix" = "$sp" ]; then
      FOUND_IN_SERVER=1
      break
    fi
  done
  if [ $FOUND_IN_SERVER -eq 0 ]; then
    UNROUTED="$UNROUTED $prefix"
  fi
done

if [ -n "$UNROUTED" ]; then
  bad "callback prefixes in menu.py NOT routed in server.py:$UNROUTED"
  printf '    These callbacks silently do nothing on the phone.\n'
else
  ok "all callback prefixes routed in server.py"
fi
echo ""

# ── 4. Fence integrity (money/identity never execute from cockpit) ───
echo "─ 4. Fence integrity"
if grep -q 'approve is Claude-only fence\|Do NOT call C.approve' "$M"; then
  ok "task:approve fenced (no DB write from cockpit)"
else
  bad "approve fence text missing — cockpit could write to coordinator DB"
fi

# Check for money/identity process execution in cockpit
MONEY_TRIGGER=0
if grep -qiE 'signalengine|introduction.?exchange' "$M" 2>/dev/null; then
  if grep -qE 'subprocess.*Popen.*(signalengine|tie)|os\.system.*(signalengine|tie)|exec\(.*(signalengine|tie)' "$M" 2>/dev/null; then
    MONEY_TRIGGER=1
  fi
fi
if [ $MONEY_TRIGGER -eq 1 ]; then
  bad "possible signalengine/tie execution trigger in menu.py"
else
  ok "no money/identity execution triggers in cockpit"
fi
echo ""

# ── 5. Full test suite (must not regress) ────────────────────────────
echo "─ 5. Full test suite"
cd "$COCKPIT"
if python3 -m pytest -q -m "not slow" --tb=no 2>/dev/null; then
  ok "full suite green"
else
  bad "full test suite FAILED — regression introduced"
fi
echo ""

# ── 6. verify_estate.sh ──────────────────────────────────────────────
echo "─ 6. Estate state probe"
VERIFY_OUT=$(bash "$HERMES/scripts/verify_estate.sh" 2>&1) || true
if echo "$VERIFY_OUT" | grep -q "VERDICT: ✅ OPERATIONAL"; then
  ok "verify_estate.sh: OPERATIONAL"
elif echo "$VERIFY_OUT" | grep "❌" | grep -qv "ACL allowlist"; then
  bad "verify_estate.sh FAILED with non-ACL errors"
else
  ok "verify_estate.sh passes except ACL (Dario lockout — tracked separately)"
fi
echo ""

# ── 7. Working tree clean ────────────────────────────────────────────
echo "─ 7. Working tree clean"
cd "$COCKPIT"
DIRTY=$(git -C "$COCKPIT" status --porcelain 2>/dev/null | { grep -v '^?? ' || true; } | wc -l | tr -d ' ')
if [ "$DIRTY" = "0" ]; then
  ok "cockpit working tree clean"
else
  bad "$DIRTY uncommitted change(s) — commit before handoff"
fi
echo ""

# ── VERDICT ──────────────────────────────────────────────────────────
echo "══════════════════════════════════════════════════════════════════"
if [ "$FAIL" = "0" ]; then
  echo "GATE: ✅ CLEAR — ready for founder handoff"
  exit 0
else
  echo "GATE: ❌ BLOCKED — fix the failures above before claiming done"
  exit 1
fi
