#!/usr/bin/env bash
# launchd's StartInterval, for a container.
#
# Usage: periodic.sh <seconds> <command...>
#
# Intervals are copied from the plists, measured 2026-08-18:
#   progress          StartInterval 3600
#   submodule-backup  StartInterval 86400
#
# A failing run must not kill the loop - launchd would simply run it again at the next
# interval, and losing an hourly snapshot is not a reason to stop taking them.
set -uo pipefail
interval="${1:?usage: periodic.sh <seconds> <command...>}"
shift
while true; do
  if ! "$@"; then
    echo "periodic: '$*' exited $? - carrying on, next run in ${interval}s" >&2
  fi
  sleep "$interval"
done
