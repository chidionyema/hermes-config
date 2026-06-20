#!/usr/bin/env python3
"""watchdog-state-probe — read-only health verdict from the watchdog's OWN recorded state.

WHY THIS EXISTS (war-room 2026-06-20: watchdog-heals-watchdog feedback loop)
  known_classes had health-watchdog -> action=auto_fix -> handler=watchdog.py. So when the
  watchdog exited non-zero (an honest signal), the dispatcher "fixed" it by RE-RUNNING the
  watchdog — under a 2s cap it can never meet (the watchdog runs heal + resolver + queue
  submits). Re-running a SENSOR heals nothing; it just re-measures, re-spawns the healer,
  and returns "still failing" every tick. A positive-feedback respawn.

  This probe breaks the loop: it READS watchdog-state.json (O(1), no subprocess, no re-run)
  and reports the last run's verdict via exit code, which the dispatcher already interprets:
    exit 0 -> healthy  (dispatcher resolves the fingerprint silently)
    exit 1 -> unhealthy: a real breach or a sustained-down window (dispatcher escalates)
    exit 2 -> STALE: the watchdog itself hasn't run within 2x cadence — it may be dead, which
              is precisely what a human must see (escalate). A sensor that stopped sensing is
              the one failure the estate cannot self-heal.

  A probe NEVER mutates state and NEVER spawns the thing it watches.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
STATE_FILE = HERMES_HOME / "logs" / "alerts" / "watchdog-state.json"

OPEN_BREACH_K = int(os.environ.get("HERMES_WD_BREACH_K", "3"))   # mirrors watchdog
SUSTAIN_N = int(os.environ.get("HERMES_WD_SUSTAIN_N", "3"))
FRESH_SECONDS = int(os.environ.get("HERMES_WD_FRESH_SECONDS", "1800"))  # 2x 15m cadence


def _parse_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _state(h):
    return h.get("state", "up" if h.get("up") else "down")  # back-compat


def verdict():
    """Return (exit_code, reason) from the watchdog's recorded state only."""
    try:
        s = json.loads(STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        # No state at all -> the watchdog has never written -> can't claim healthy.
        return 2, "no watchdog state (watchdog may never have run)"

    hist = s.get("daemon_history", [])
    last_ts = _parse_iso(hist[-1].get("ts")) if hist else None
    if not last_ts:
        return 2, "watchdog state has no timestamped history"
    age = (datetime.now(timezone.utc) - last_ts).total_seconds()
    if age > FRESH_SECONDS:
        return 2, f"watchdog stale: last run {int(age)}s ago (> {FRESH_SECONDS}s)"

    # Sustained-liveness over the last N KNOWN readings (UNKNOWN excluded — load noise
    # must not read as down; same rule as the watchdog and the gateway verifier).
    known = [h for h in hist if _state(h) in ("up", "down")][-SUSTAIN_N:]
    if len(known) >= SUSTAIN_N and not all(_state(h) == "up" for h in known):
        return 1, "gateway not sustained-alive over last %d known runs" % SUSTAIN_N

    # Any open fingerprint breaching the K-run SLA is an unhealed condition.
    for fp, rec in (s.get("fingerprints") or {}).items():
        if rec.get("present_streak", 0) >= OPEN_BREACH_K:
            return 1, "open alert breaching SLA: %s" % (rec.get("sample", fp)[:80])

    return 0, "healthy: watchdog fresh, gateway sustained, no breach"


def main():
    code, reason = verdict()
    # Probe contract: silent on healthy (exit 0); speak only when surfacing.
    if code != 0:
        print(f"watchdog-state-probe: {reason}")
    return code


if __name__ == "__main__":
    sys.exit(main())
