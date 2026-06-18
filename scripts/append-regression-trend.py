#!/usr/bin/env python3
"""
append-regression-trend.py — Appends coverage % + timestamp to regression-trend.jsonl.

Called by self-regression.py --report after generating the report.
Creates the trend file if it doesn't exist.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
TREND_FILE = HERMES_HOME / "logs" / "regression-trend.jsonl"

def append_trend(coverage_pct: float, passed: int, total: int, source: str = "self-regression"):
    entry = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "coverage_pct": round(coverage_pct, 1),
        "passed": passed,
        "total": total,
        "source": source,
    }
    os.makedirs(TREND_FILE.parent, exist_ok=True)
    with open(TREND_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"  📈 Trend appended: {coverage_pct:.0f}% ({passed}/{total})")
    return 0


def main():
    if len(sys.argv) >= 4:
        pct = float(sys.argv[1])
        passed = int(sys.argv[2])
        total = int(sys.argv[3])
    elif len(sys.argv) == 2 and sys.argv[1] == "--parse-report":
        # Parse latest regression report
        report_path = HERMES_HOME / "logs" / "regression-report.md"
        if not report_path.exists():
            print("No regression report found.")
            return 1
        with open(report_path) as f:
            content = f.read()
        pct, passed, total = 0.0, 0, 0
        for line in content.split("\n"):
            if "Coverage:" in line:
                parts = line.strip().split()
                for p in parts:
                    if "/" in p:
                        nums = p.split("/")
                        passed_val = int(nums[0])
                        total_val = int(nums[1].rstrip(")"))
                        break
                for p in parts:
                    if "%" in p:
                        pct_val = float(p.strip("()%"))
                        break
                pct, passed, total = pct_val, passed_val, total_val
                break
        if total == 0:
            print("Could not parse coverage from report.")
            return 1
    else:
        print("Usage: append-regression-trend.py <coverage_pct> <passed> <total>")
        print("   or: append-regression-trend.py --parse-report")
        return 1

    return append_trend(pct, passed, total)


if __name__ == "__main__":
    sys.exit(main())
