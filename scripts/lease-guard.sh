#!/usr/bin/env bash
# The laptop side of the leader lease, run on a timer by ai.hermes.lease-guard.
#
# It does two things and nothing else: write down who actually holds the lease, and — if this
# machine does not hold it — stop any Hermes daemon that has come back. That is the difference
# between "the laptop was turned off on 2026-08-19" and "the laptop cannot be a second estate".
# launchctl enable, a reinstall script or a restored backup can all undo a manual bootout. This
# undoes them back, every five minutes, without a human.
#
# It never STARTS anything. A laptop that promotes itself because it briefly could not reach R2
# is exactly the split-brain this is here to prevent, and hermes_lease.py raises rather than
# treating an unreadable lease as a free one.
set -uo pipefail
HERMES="${HERMES_HOME:-$HOME/.hermes}"
cd "$HERMES" || exit 2

# The R2 credentials live in the env file, never in the plist: a plist is world-readable.
set -a
# shellcheck disable=SC1091
[ -r "$HERMES/.env" ] && . "$HERMES/.env"
set +a

"$HERMES/hermes-agent/venv/bin/python" "$HERMES/scripts/hermes_lease.py" acquire --enforce
rc=$?

# EXIT CODES ARE TRANSLATED ON PURPOSE. hermes_lease.py answers "do I hold the lease": 0 yes,
# 1 someone else, 2 cannot see. On this laptop the HEALTHY answer is 1 - Fly is the primary and
# this machine correctly stands down. Passing that through would make launchd record a failing
# job every five minutes, and the estate probe would grade a working fence as broken.
#
# 2 is the one that must stay loud: not being able to read the lease means this machine cannot
# know whether it is allowed to run, and that is a real fault.
case "$rc" in
  0|1) exit 0 ;;
  *)   exit "$rc" ;;
esac
