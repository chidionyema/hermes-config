"""memory-hygiene — enforce a last_verified stamp on every memory entry. Item 6.

Memory entries (MEMORY.md, §-separated) must carry a verification stamp so a stale
fact is re-verified or expired rather than trusted forever. Convention enforced:
each entry contains `[verified: YYYY-MM-DD]`. The probe flags entries that are
UNVERIFIED (no stamp) or STALE (stamp older than VERIFY_TTL_DAYS, default 30).

Exit 0 = all entries fresh. Exit 1 = entries need re-verify/expire (escalated to queue).
This is the substrate that makes "re-verify or expire" enforceable; Otto does the
actual re-verification on the flagged entries.
"""
import os
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

HERMES = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
MEMORY = HERMES / "memories" / "MEMORY.md"
QUEUE = HERMES / "scripts" / "hermes_queue.py"
TTL_DAYS = int(os.environ.get("HERMES_VERIFY_TTL_DAYS", "30"))
STAMP = re.compile(r"\[verified:\s*(\d{4}-\d{2}-\d{2})\s*\]")


def main():
    if not MEMORY.exists():
        print("memory-hygiene: no MEMORY.md — PASS")
        return 0
    entries = [e.strip() for e in MEMORY.read_text().split("§") if e.strip()]
    today = date.today()
    unverified = stale = 0
    for e in entries:
        m = STAMP.search(e)
        if not m:
            unverified += 1
            continue
        try:
            age = (today - datetime.strptime(m.group(1), "%Y-%m-%d").date()).days
        except ValueError:
            unverified += 1
            continue
        if age > TTL_DAYS:
            stale += 1

    flagged = unverified + stale
    if flagged == 0:
        print(f"memory-hygiene: {len(entries)} entries, all verified within {TTL_DAYS}d — PASS")
        return 0

    msg = (f"{flagged}/{len(entries)} memory entries need re-verify/expire "
           f"({unverified} unstamped, {stale} stale > {TTL_DAYS}d)")
    if QUEUE.exists():
        subprocess.run([sys.executable, str(QUEUE), "submit", "--source", "memory-hygiene",
                        "--severity", "warn", "--message", msg], capture_output=True)
    print(f"memory-hygiene: FAIL — {msg}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
