#!/usr/bin/env python3
"""proving-ground-probe — READ-ONLY verdict for the proving-ground failure class.

STRUCTURAL FIX (war-room 2026-06-20 — last heavy-probe fire)
  known_classes pointed the proving-ground PROBE at proving-ground.py itself, which runs
  `npm test` / `npm run build` / `uv run pytest` across 5 repos. Under otto-dispatch's 2s
  handler cap that can NEVER finish: it was killpg'd every tick, always returned non-zero
  ("still failing" -> re-fired + escalated), and spawned a 5-repo test storm every dispatch.
  Identical shape to the repo-health pytest-storm that melted the box.

  A dispatcher probe VERIFIES state; it never RE-RUNS the workload. proving-ground.py stays
  the SCHEDULED auditor (runs the suite on its own cron, writes a dated receipt). This probe
  only READS the latest receipt and reports the recorded verdict via exit code:
    0 -> PASS         (latest receipt fresh, no required failure)
    1 -> FAIL         (a required check failed or a required path is missing)
    2 -> STALE/ABSENT (no fresh receipt -> the auditor itself hasn't run -> escalate; an
                       auditor that stopped auditing is exactly what a human must see)
"""
import json
import os
import sys
import time
from pathlib import Path

RECEIPTS = Path(os.environ.get("HERMES_PG_RECEIPTS",
                               os.path.expanduser("~/.lux/proving-ground")))
# proving-ground runs ~daily; allow 1.5 days before the last receipt is "stale".
FRESH_SECONDS = int(os.environ.get("HERMES_PG_FRESH_SECONDS", str(36 * 3600)))


def _latest_receipt():
    if not RECEIPTS.is_dir():
        return None
    receipts = sorted(RECEIPTS.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return receipts[0] if receipts else None


def verdict():
    r = _latest_receipt()
    if r is None:
        return 2, "no proving-ground receipt (auditor may never have run)"
    age = time.time() - r.stat().st_mtime
    if age > FRESH_SECONDS:
        return 2, f"proving-ground stale: latest receipt {int(age / 3600)}h old (> {FRESH_SECONDS // 3600}h)"
    try:
        rows = [json.loads(l) for l in r.read_text().splitlines() if l.strip()]
    except (OSError, json.JSONDecodeError) as e:
        return 2, f"unreadable proving-ground receipt: {e}"

    missing_required = [x for x in rows if x.get("state") == "missing" and x.get("required")]
    failed_required = [x for x in rows if x.get("state") == "fail" and x.get("required")]
    if missing_required or failed_required:
        bad = (failed_required + missing_required)[0]
        return 1, "proving-ground FAIL: %s/%s %s" % (
            bad.get("project"), bad.get("check"), bad.get("state"))
    ok = sum(1 for x in rows if x.get("state") == "pass")
    return 0, f"proving-ground PASS: {ok}/{len(rows)} checks (receipt {r.name})"


def main():
    code, reason = verdict()
    if code != 0:
        print(f"proving-ground-probe: {reason}")
    return code


if __name__ == "__main__":
    sys.exit(main())
