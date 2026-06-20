#!/usr/bin/env python3
"""repo-health-probe — READ-ONLY verifier for the repo-health failure class.

STRUCTURAL FIX (2026-06-19): a dispatcher "probe" must VERIFY state, never RE-RUN
the workload. The registry previously pointed the repo-health probe at
repo-health-check.py itself — the full 3-repo pytest suite — under otto-dispatch's
2s handler cap. That can never finish in 2s, so it ALWAYS returned non-zero (never
resolved → re-fired every tick) AND it spawned fresh pytest every 5 minutes which,
before the process-group fix, orphaned and melted the box.

This probe instead reads the most recent repo-health.jsonl entry (written by the
real cron run) and grades it:
    exit 0  — latest run shows NO repo in "fail" state (healthy / dirty / skip ok)
    exit 1  — latest run shows >=1 repo failing, OR no history yet to prove health

It runs in milliseconds, spawns nothing, and is safe to call on every dispatch tick.
"""
import json
import os
import sys
from pathlib import Path

HERMES = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
HISTORY = HERMES / "logs" / "health" / "repo-health.jsonl"


def main():
    if not HISTORY.exists():
        return 1  # can't prove healthy
    try:
        lines = HISTORY.read_text().splitlines()
        last = json.loads(lines[-1]) if lines else {}
    except (OSError, json.JSONDecodeError, IndexError):
        return 1
    results = last.get("results", {})
    if not results:
        return 1
    failing = [n for n, r in results.items() if r.get("state") == "fail"]
    if failing:
        print(f"repo-health-probe: still failing: {', '.join(failing)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
