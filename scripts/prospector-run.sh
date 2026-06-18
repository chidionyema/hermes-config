#!/bin/bash
# prospector-run.sh — guarded runner for prospector-daily-generation (Ball: 5b).
#
# ROOT CAUSE THIS REPLACES: the cron's `script` field held an inline shell command
# ("cd ~/... && uv run ... || echo 'failed' && ..."). The runner treats `script` as a
# FILENAME, so it failed every run with "Script not found"; and even as a command the
# mid-chain `|| echo` returned 0, MASKING real failures (last_status read "ok"). This
# script is a real file with a preflight guard, a strict budget, and honest escalation
# to the relay queue — never a masked echo.
set -uo pipefail
REPO="$HOME/Documents/code/prospector"
Q="$HOME/.hermes/scripts/hermes_queue.py"
BUDGET=110   # seconds, under the 120s cron cap

submit() { python3 "$Q" submit --source prospector-generation "$@" >/dev/null 2>&1 || true; }

# Preflight: missing repo is a real, surfaced condition — not a silent pass.
if [ ! -d "$REPO" ]; then
  submit --severity warn --message "prospector repo missing at $REPO — generation skipped"
  echo "prospector: repo missing ($REPO) — escalated to relay queue, skipping." >&2
  exit 0   # silent to the user; the queue carries the actionable
fi

cd "$REPO" || { submit --severity error --message "prospector: cannot cd $REPO"; exit 1; }
unset VIRTUAL_ENV

# Single canonical invocation under a strict timeout. No fallback chain masking errors.
OUT=$(timeout "$BUDGET" uv run python -m prospector.generate --count 20 2>&1); rc=$?

if [ "$rc" = 124 ]; then
  submit --severity warn --message "prospector generation exceeded ${BUDGET}s budget (cron cap)"
  echo "prospector: timed out after ${BUDGET}s" >&2
  exit 1
elif [ "$rc" != 0 ]; then
  TAIL=$(printf '%s\n' "$OUT" | tail -3 | tr '\n' ' ')
  submit --severity error --message "prospector generation failed (exit $rc): ${TAIL:0:160}"
  echo "prospector: failed exit $rc" >&2
  exit "$rc"
fi

echo "prospector: generation ok"
exit 0
