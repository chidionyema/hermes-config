#!/usr/bin/env python3
"""watchdog-cron.py — cron-boundary wrapper for watchdog.py (exit-contract fix).

ROOT CAUSE it fixes (the recurring false "failure: health-watchdog" task)
  watchdog.py is exit-code-honest: it returns 1 when an estate alert has been OPEN
  for >=K runs and 2 on a gateway restart-loop. Those codes are a HEALTH GRADE about
  OTHER services — and they are ALREADY delivered through dedicated channels: the relay
  queue (watchdog.submit_to_queue), the recorded state file (watchdog-state.json), and
  the authoritative read-only verdict in watchdog-state-probe.py. But cron's scheduler
  (hermes-agent/cron/scheduler.py:991) treats ANY nonzero script exit as "this job
  FAILED", so every window in which some OTHER cron job is unhealthy made cron mark the
  health-watchdog job itself errored -> a FALSE "failure: health-watchdog" task
  (strategist audit R3, 2026-06-20; recommendation #5: "add a wrapper that re-maps
  exit 1 -> exit 0 for cron when the error is just 'alerts exist'").

  This wrapper makes the CRON exit code answer cron's ACTUAL question — "did the
  watchdog itself operate?" — instead of overloading it with the estate's health grade:
    • watchdog ran and graded (returned 0/1/2)  -> exit 0  (findings are relayed elsewhere)
    • watchdog raised / crashed / bad grade      -> exit 1  (a real operational failure
                                                             cron SHOULD flag: a blind sensor)

  The health verdict stays watchdog-state-probe.py's job (it reads the state file), and
  watchdog.py's own tested exit codes (tests/test_watchdog.py) are deliberately untouched.
  Point the health-watchdog cron job's `script` at THIS file, not watchdog.py.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> int:
    import watchdog  # same scripts/ dir; imported (not subprocessed) so a traceback
                     # exit-1 is distinguishable from watchdog's graded exit-1.
    try:
        grade = watchdog.main()
    except Exception as exc:  # the watchdog ITSELF broke — that genuinely is a job failure
        print(f"health-watchdog operational failure: {exc!r}", file=sys.stderr)
        return 1
    if grade not in (0, 1, 2):
        # An out-of-contract grade is itself a defect worth surfacing to cron.
        print(f"health-watchdog unexpected grade {grade!r}", file=sys.stderr)
        return 1
    # grade in {0,1,2}: the watchdog ran and reported. Findings (open breach / restart
    # loop) are delivered via the relay queue + state file + probe — the cron JOB
    # succeeded, so exit 0 and stop spawning the false self-failure task.
    return 0


if __name__ == "__main__":
    sys.exit(main())
