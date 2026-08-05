#!/bin/bash
# Hourly self-improvement cycle: gap-finding → auto-close, self-regression,
# meta-improver velocity/health, policy effectiveness.
#
# Why this wrapper exists (2026-08-05): the cron job `self-improve-runner` had
#   "script": "python3 scripts/self_improve_runner.py --hourly"
# but cron/scheduler.py::_run_job_script treats `script` as a BARE FILENAME
# resolved under ~/.hermes/scripts/ and picks the interpreter from the file
# extension — it never splits the string into argv. So the scheduler looked for
# a file literally named "python3 scripts/self_improve_runner.py --hourly" and
# failed every hour with "Script not found" from 2026-08-03 until this landed.
# Arguments therefore have to live inside a wrapper like this one.
#
# Silent when healthy: cron delivers stdout, so keep normal runs quiet and let
# the runner's own logs carry the detail.
set -euo pipefail
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
exec /usr/local/bin/python3 "$HERMES_HOME/scripts/self_improve_runner.py" --hourly
