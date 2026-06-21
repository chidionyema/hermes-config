#!/bin/bash
# weekly-lux-verify.sh — Weekly `lux verify` across all projects with specs.
#
# Extracted from cron job ca7dde96adcf ("Run lux verify on all projects with
# specs"), whose `script` field had wrongly held this bash BODY inline. The cron
# runner (hermes-agent/cron/scheduler.py) resolves `script` as a FILE under
# ~/.hermes/scripts/ and ignores shebangs, so an inline body resolved to a
# non-existent path and the job errored every run ("Script not found").
#
# This is a REPORT job: per-project verify failures are captured as output, not
# treated as a script crash (guarded with `|| true`), so a real spec failure is
# reported to the operator rather than re-surfacing as a health-watchdog
# CRON_ERROR. Script exits 0 as long as it ran.
set -u

run_project() {
  local label="$1" dir="$2"; shift 2
  echo "=== ${label} ==="
  if [ ! -d "${dir}" ]; then
    echo "  skipped: ${dir} not found"
    return 0
  fi
  ( cd "${dir}" && "$@" 2>&1 | tail -5 ) || echo "  ${label} verify reported failures (see above)"
}

run_project "LUX"           "${HOME}/Documents/code/lux"          npm run lux -- spec verify
run_project "Signal Engine" "${HOME}/Documents/code/signalengine" uv run lux-spec spec verify
run_project "Prospector"    "${HOME}/Documents/code/prospector"   uv run lux-spec spec verify

exit 0
