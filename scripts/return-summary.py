#!/usr/bin/env python3
"""
return-summary.py — "What happened while I was away?" probe.

Called by otto-inbound when the user's first message comes after >1h idle.
Composes data from ops-monitor, prospector ticks, and cron health into a
single one-line summary appended under Otto's response.

Output: plain text one-liner, e.g.:
  _While away (95m): 🔭 moat down · 4 cron errors · 💰 $6.03 spent · ⏸ auto-paused_
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
PROSPECTOR_TICKS = Path.home() / "Documents/code/prospector/store/scheduler/ticks.jsonl"
PROSPECTOR_PAUSE = Path.home() / "Documents/code/prospector/store/scheduler/PAUSE"
CRON_JOBS = HERMES_HOME / "cron" / "jobs.json"
OPS_LOG = HERMES_HOME / "logs" / "ops-monitor.jsonl"
ERROR_LOG = HERMES_HOME / "logs" / "errors.log"


def summary_since(cutoff_hours: int = 1) -> str:
    """Build a one-line summary of what happened since cutoff_hours ago."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=cutoff_hours)
    parts = []

    # Prospector moat
    try:
        if PROSPECTOR_TICKS.is_file():
            lines = PROSPECTOR_TICKS.read_text().splitlines()
            errors = 0
            total = 0
            for ln in reversed(lines):
                try:
                    t = json.loads(ln)
                    ts = datetime.fromisoformat(str(t.get("ts", "")).replace("Z", "+00:00"))
                    if ts < cutoff:
                        break
                    total += 1
                    if t.get("error"):
                        errors += 1
                except Exception:
                    continue
            if errors > 0 and errors >= total * 0.5:
                parts.append(f"🔭 moat down ({errors}/{total} ticks)")
    except Exception:
        pass

    # Cron health
    try:
        if CRON_JOBS.is_file():
            data = json.loads(CRON_JOBS.read_text())
            jobs = data if isinstance(data, list) else data.get("jobs", [])
            failing = sum(1 for j in jobs
                         if j.get("enabled", True)
                         and j.get("last_status") not in (None, "", "ok"))
            if failing > 0:
                parts.append(f"{failing} cron errors")
    except Exception:
        pass

    # Spend
    try:
        if PROSPECTOR_TICKS.is_file():
            lines = PROSPECTOR_TICKS.read_text().splitlines()
            spent = 0.0
            for ln in reversed(lines):
                try:
                    t = json.loads(ln)
                    spent = max(spent, float(t.get("today_spend_usd", 0) or 0))
                except Exception:
                    continue
            if spent > 0:
                parts.append(f"💰 ${spent:.2f} spent")
    except Exception:
        pass

    # Auto-pause
    if PROSPECTOR_PAUSE.is_file():
        parts.append("⏸ auto-paused")

    # API credits
    try:
        if OPS_LOG.is_file():
            ops_lines = OPS_LOG.read_text().splitlines()
            credit_issues = False
            for ln in ops_lines[-20:]:
                try:
                    entry = json.loads(ln)
                    ts = datetime.fromisoformat(str(entry.get("ts", "")).replace("Z", "+00:00"))
                    if ts >= cutoff and "credit" in str(entry.get("detail", "")).lower():
                        credit_issues = True
                        break
                except Exception:
                    continue
            if credit_issues:
                parts.append("💳 credits low")
    except Exception:
        pass

    if not parts:
        return "_All quiet while you were away._"

    return "_While away: " + " · ".join(parts) + "_"


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Return summary probe")
    parser.add_argument("--hours", type=int, default=1, help="Hours since last activity")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = summary_since(args.hours)
    if args.json:
        print(json.dumps({"summary": result}))
    else:
        print(result)


if __name__ == "__main__":
    main()
