#!/bin/bash
# prospector-run.sh — hourly guard/liveness probe for prospector generation (Ball: 5b).
#
# ROOT CAUSE THIS REPLACES (#1, fixed earlier): the cron's `script` field held an inline shell
# command whose mid-chain `|| echo` returned 0, MASKING real failures. This script is a real file
# with a preflight guard and honest escalation to the relay queue — never a masked echo.
#
# ROOT CAUSE THIS REPLACES (#2, 2026-06-21 — "exceeded 110s budget"): this tick used to run a REAL
# grounded batch (`run_scheduled --once`, no --dry-run). But a grounded batch is a multi-minute,
# 100k+-token job (observed: 447k tokens / 109 calls / 60+ candidates ruled per batch; the engine's
# own watchdog allows up to 45 min for one). It CANNOT fit in the 110s budget under the 120s cron
# cap, so every hourly run timed out (rc=124) → "prospector generation exceeded 110s budget".
# Worse, it DUPLICATED the always-on `com.prospector.scheduler` launchd daemon, which already owns
# real generation unbounded (--daemon, KeepAlive, 2h cadence, proven producing). So this cron now
# runs ONLY the guard in --dry-run: evaluate the spend ceiling + PAUSE switch and write a tick,
# sub-second, never generating. Real generation stays with the daemon; liveness with the watchdog.
set -uo pipefail
REPO="$HOME/Documents/code/prospector"
Q="$HOME/.hermes/scripts/hermes_queue.py"
BUDGET=110   # seconds, under the 120s cron cap — a safety net only; --dry-run finishes in <2s

submit() { python3 "$Q" submit --source prospector-generation "$@" >/dev/null 2>&1 || true; }

# Preflight: missing repo is a real, surfaced condition — not a silent pass.
if [ ! -d "$REPO" ]; then
  submit --severity warn --message "prospector repo missing at $REPO — generation skipped"
  echo "prospector: repo missing ($REPO) — escalated to relay queue, skipping." >&2
  exit 0   # silent to the user; the queue carries the actionable
fi

cd "$REPO" || { submit --severity error --message "prospector: cannot cd $REPO"; exit 1; }
# Drop a stale CWD handle if the repo dir was unlinked+recreated (inode swap) mid-run.
if ! pwd -P >/dev/null 2>&1; then
  cd / && cd "$REPO" || { submit --severity error --message "prospector: CWD unresolvable at $REPO"; exit 1; }
fi
unset VIRTUAL_ENV

# Single canonical invocation under a strict timeout. `--directory` pins uv to the repo so an
# inode-swap race on the inherited CWD can't abort it with "Current directory does not exist".
# No fallback chain masking errors.
#
# --dry-run is the load-bearing flag (2026-06-21): run_scheduled evaluates the guard (spend ceiling
# + PAUSE switch), writes one tick, and exits — it does NOT generate. This is a guard/liveness probe
# that completes in <2s, so the 110s budget can never be exceeded. Real grounded generation is owned
# by the always-on `com.prospector.scheduler` daemon (--daemon, unbounded). Running --once here would
# re-do that multi-minute batch in a 110s box and time out every run (the bug this replaces).
OUT=$(timeout "$BUDGET" uv run --directory "$REPO" python -m prospector.scheduler.run_scheduled --once --dry-run 2>&1); rc=$?

if [ "$rc" = 124 ]; then
  # Should be unreachable for a --dry-run guard eval; if it ever fires, the guard/ledger read itself
  # is hung — a real, surfaced condition, not masked.
  submit --severity warn --message "prospector guard probe exceeded ${BUDGET}s budget (ledger read hung?)"
  echo "prospector: guard probe timed out after ${BUDGET}s" >&2
  exit 1
elif [ "$rc" != 0 ]; then
  TAIL=$(printf '%s\n' "$OUT" | tail -3 | tr '\n' ' ')
  # Transient CWD inode-swap race (repo being rewritten concurrently) self-heals next run:
  # named terminal state = transient/retry, surfaced as warn — NOT a hard error escalation.
  if printf '%s' "$OUT" | grep -qi 'current directory does not exist'; then
    submit --severity warn --message "prospector: transient CWD race (repo rewrite) — will retry next run"
    echo "prospector: transient CWD race — surfaced as warn, retrying next run" >&2
    exit 0
  fi
  submit --severity error --message "prospector guard probe failed (exit $rc): ${TAIL:0:160}"
  echo "prospector: guard probe failed exit $rc" >&2
  exit "$rc"
fi

echo "prospector: guard probe ok (real generation owned by com.prospector.scheduler daemon)"
exit 0
