#!/usr/bin/env python3
"""cron-job-health-probe — read-only probe for CRON_SILENT / CRON_ERROR classes.

Exit 0 when the referenced Hermes cron job is healthy again (last_status=ok)
or intentionally paused/disabled — so the coordinator can auto-resolve the
escalation without paging the founder. Exit 1 if still broken / unknown.

Usage (from known_classes / otto-dispatch):
  cron-job-health-probe.py <source_or_title_haystack>
"""
from __future__ import annotations

import json
import os
import re
import sys

HERMES = os.path.expanduser(os.environ.get("HERMES_HOME", "~/.hermes"))
JOBS = os.path.join(HERMES, "cron", "jobs.json")


def _load_jobs() -> list:
    try:
        data = json.load(open(JOBS))
        return list(data.get("jobs") or [])
    except Exception:
        return []


def _extract_job_hint(hay: str) -> str:
    """Pull a job name/id fragment from CRON_* messages."""
    hay = hay or ""
    m = re.search(
        r"CRON_(?:SILENT_STRETCH|ERROR):\s*([^:\n]+?)(?:\s+(?:missed|errored)|$)",
        hay,
        re.I,
    )
    if m:
        return m.group(1).strip()
    # source form: health-watchdog: cron_error: <something>
    m = re.search(r"cron_(?:silent|error)[:\s]+([^\n]+)", hay, re.I)
    if m:
        return m.group(1).strip()[:80]
    return ""


def job_is_healthy(hint: str, jobs: list) -> bool | None:
    """True=healthy, False=still bad, None=can't match."""
    if not hint:
        return None
    hint_l = hint.lower()
    for j in jobs:
        name = (j.get("name") or "")
        jid = (j.get("id") or "")
        if hint_l not in name.lower() and hint_l not in jid.lower() and name.lower() not in hint_l:
            continue
        # Intentionally paused / disabled → treat as resolved (not an open wound)
        if j.get("state") == "paused" or j.get("enabled") is False:
            return True
        status = (j.get("last_status") or "").lower()
        if status in ("ok", "success", "skipped"):
            return True
        if status in ("error", "failed", "failure"):
            return False
        # unknown last_status but job is scheduled — not proven healthy
        return False
    return None


def main() -> int:
    hay = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else sys.stdin.read()
    hint = _extract_job_hint(hay)
    jobs = _load_jobs()
    verdict = job_is_healthy(hint, jobs)
    if verdict is True:
        print(f"ok: job healthy or paused ({hint!r})")
        return 0
    if verdict is False:
        print(f"fail: job still unhealthy ({hint!r})")
        return 1
    # Can't match — don't pretend; leave escalated for human / next class
    print(f"unknown: no job match for {hint!r}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
