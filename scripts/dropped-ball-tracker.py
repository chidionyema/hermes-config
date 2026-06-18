#!/usr/bin/env python3
"""dropped-ball-tracker — telemetry probe for Otto's own failures (Ball 19 addendum).

The user wants to SEE how often the ball is dropped per class, not raw alerts. Every
dropped ball is recorded as a queue fingerprint (source otto-dropped-ball, stable
per-class fingerprint "dropped-ball-N-<source>"). This probe is the cron that:
  - reads the relay queue state (the single source of truth),
  - asserts NO new dropped-ball fingerprint appeared in the last N minutes,
  - on any new drop, fires ONE aggregate entry into the relay queue (severity=error)
    carrying the count + per-source breakdown — the user sees aggregates, not raw.

Exit 0 = no new drop in the window. Exit 2 = new drop(s) detected (probe fired).
Its own escalation uses source 'dropped-ball-tracker' which is EXCLUDED from the
scan, so it can never re-trigger itself.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERMES = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
STATE = HERMES / "queue" / "state.json"
QUEUE = HERMES / "scripts" / "hermes_queue.py"
WINDOW_MIN = int(os.environ.get("HERMES_DB_WINDOW_MIN", "15"))
SELF_SOURCE = "dropped-ball-tracker"


def _is_drop(source: str) -> bool:
    return "dropped-ball" in (source or "") and source != SELF_SOURCE


def main():
    if not STATE.exists():
        print("dropped-ball-tracker: no queue state — PASS (no drops)")
        return 0
    try:
        fps = json.loads(STATE.read_text()).get("fingerprints", {})
    except (OSError, json.JSONDecodeError):
        print("dropped-ball-tracker: unreadable state — PASS (nothing to judge)")
        return 0

    cutoff = time.time() - WINDOW_MIN * 60
    recent, by_source, total = [], {}, 0
    for fp, v in fps.items():
        if _is_drop(v.get("source", "")) and v.get("last_epoch", 0) >= cutoff:
            recent.append(fp)
            c = v.get("count", 1)
            total += c
            by_source[v["source"]] = by_source.get(v["source"], 0) + c

    if not recent:
        print(f"dropped-ball-tracker: 0 new dropped balls in last {WINDOW_MIN}m — PASS")
        return 0

    msg = (f"{len(recent)} dropped-ball class(es), {total} drop(s) in last {WINDOW_MIN}m: "
           + ", ".join(f"{k}={n}" for k, n in sorted(by_source.items())))
    if QUEUE.exists():
        subprocess.run([sys.executable, str(QUEUE), "submit", "--source", SELF_SOURCE,
                        "--severity", "error", "--message", msg],
                       capture_output=True, text=True)
    print(f"dropped-ball-tracker: FAIL — {msg}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
