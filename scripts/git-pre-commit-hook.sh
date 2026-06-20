#!/usr/bin/env bash
# pre-commit guard for the Hermes estate. Two jobs:
#   1) COMPILE GATE  — reject any staged .py that does not parse.
#   2) LANE GUARD    — reject edits to Claude's single-writer lane unless HERMES_LANE=claude.
#
# WHY: (1) an agent committed gateway/platforms/telegram.py with an empty `else:`;
# it would not import, so launchd crash-looped the gateway and the Telegram bot went
# offline while the agent reported "all tests pass, clean tree". (2) concurrent agents
# editing shared core files (coordinator.py, gateway/**) has broken prod more than once.
# These make both failure modes impossible to commit by accident, for ANY agent.
set -eu

PY="$HOME/.hermes/hermes-agent/venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3 || true)"

# ── 1. COMPILE GATE ───────────────────────────────────────────────────────────
if [ -n "${PY:-}" ]; then
  pyfiles=$(git diff --cached --name-only --diff-filter=ACM -- '*.py' || true)
  if [ -n "$pyfiles" ]; then
    tmp="$(mktemp)"; fail=0
    while IFS= read -r f; do
      [ -n "$f" ] || continue
      [ -f "$f" ] || continue
      if ! "$PY" -c 'import sys; compile(open(sys.argv[1]).read(), sys.argv[1], "exec")' "$f" 2>"$tmp"; then
        echo "X pre-commit: $f does not parse:" >&2
        sed 's/^/    /' "$tmp" >&2
        fail=1
      fi
    done <<EOF
$pyfiles
EOF
    rm -f "$tmp"
    if [ "$fail" -ne 0 ]; then
      echo "" >&2
      echo "COMMIT BLOCKED: Python syntax error(s) above. This guard exists because a" >&2
      echo "syntax-broken commit once crash-looped the Hermes gateway. Fix, then re-commit." >&2
      echo "(deliberate escape hatch only: git commit --no-verify)" >&2
      exit 1
    fi
  fi
fi

# ── 2. LANE GUARD ─────────────────────────────────────────────────────────────
# Claude's single-writer lane. Commits touching these require HERMES_LANE=claude.
PROTECTED_RE='^(scripts/coordinator\.py|config\.yaml|plugins/otto-inbound/|gateway/)'
if [ "${HERMES_LANE:-}" != "claude" ]; then
  allfiles=$(git diff --cached --name-only --diff-filter=ACM || true)
  protected=$(printf '%s\n' "$allfiles" | grep -E "$PROTECTED_RE" || true)
  if [ -n "$protected" ]; then
    echo "X pre-commit LANE GUARD: these files are in Claude's single-writer lane:" >&2
    printf '%s\n' "$protected" | sed 's/^/    /' >&2
    echo "" >&2
    echo "Concurrent edits to these have broken production more than once." >&2
    echo "If you are Claude:        HERMES_LANE=claude git commit ..." >&2
    echo "Otherwise: leave them to Claude (or coordinate first). Escape: git commit --no-verify" >&2
    exit 1
  fi
fi

exit 0
