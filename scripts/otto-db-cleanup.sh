#!/bin/bash
# Daily DB TTL cleanup (30-day-old sessions) + gzip backup of state.db and
# coordinator.db into ~/.hermes/backups (db_health.py keeps the last 7).
#
# Why this wrapper exists (2026-08-05): the cron job `otto-db-cleanup` carried
# its work in a "command" field. Nothing in cron/scheduler.py reads "command" —
# the no_agent path reads "script" (scheduler.py:1335) and the job had neither
# "script" nor "no_agent", so it fell through to the agent path and reported
# last_status "ok" every single day without running anything. Proof it was a
# no-op: on 2026-08-05 the job reported ok at 03:01, and the newest dated file
# in ~/.hermes/backups was from 2 Aug. An unread field that reports success is
# worse than a missing job — do not reintroduce "command".
#
# Output is JSON on stdout; the job is deliver=local, so it is logged, not sent.
set -euo pipefail
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
exec /usr/local/bin/python3 "$HERMES_HOME/scripts/db_health.py" --cleanup --backup --json
