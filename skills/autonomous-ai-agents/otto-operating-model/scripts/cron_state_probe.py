#!/usr/bin/env python3
"""Cron-state diagnostic probe for strategist audits.

Usage:
    python3 cron_state_probe.py                    # default: full audit
    python3 cron_state_probe.py --job 85385abb646d # specific job
    python3 cron_state_probe.py --stale 2          # jobs with last_run_at > N days

Designed to distinguish sub-mode A (silent-stretch, no file) from sub-mode B
(errors-post-write, file landed but last_status: error). See SKILL §12.

Run as the FIRST probe at audit-start. Output is the answer — return verbatim,
do not narrate.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERMES = Path.home() / ".hermes"
JOBS_FILE = HERMES / "cron" / "jobs.json"
STATE_FILE = HERMES / "logs" / "alerts" / "watchdog-state.json"
REPORTS_DIR = HERMES / "reports"


def load_jobs() -> list[dict]:
    with open(JOBS_FILE) as f:
        return json.load(f)["jobs"]


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    with open(STATE_FILE) as f:
        return json.load(f)


def parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def diagnose_job(job: dict, state: dict) -> dict:
    jid = job.get("id")
    name = job.get("name", "?")
    last_run = parse_ts(job.get("last_run_at"))
    last_status = job.get("last_status", "?")
    paused_at = parse_ts(job.get("paused_at"))
    streak_info = state.get("fast_forward_streaks", {}).get(jid, {})
    ff_streak = streak_info.get("streak", 0)

    # Sub-mode classification
    sub_mode = None
    if last_run and last_status == "ok":
        # Check watchdog-state streak (more recent than jobs.json)
        ws_run = parse_ts(streak_info.get("run_at"))
        if ws_run and (datetime.now(timezone.utc) - ws_run) > timedelta(days=2):
            sub_mode = "A-SILENT_STRETCH"
        else:
            # Check if expected report file exists (only for report-emitting jobs)
            report_path = None
            if "audit" in name.lower() or "report" in name.lower():
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                candidate = REPORTS_DIR / f"{name}-{today}.md"
                if not candidate.exists():
                    sub_mode = "A-SILENT_STRETCH_NO_FILE"
    elif last_status == "error":
        sub_mode = "B-ERRORS_POST_WRITE"

    return {
        "id": jid[:8] if jid else "?",
        "name": name,
        "schedule": job.get("schedule_display", "?"),
        "last_run_at": job.get("last_run_at"),
        "last_status": last_status,
        "paused_at": job.get("paused_at"),
        "ff_streak": ff_streak,
        "days_since_run": (
            (datetime.now(timezone.utc) - last_run).days if last_run else None
        ),
        "sub_mode": sub_mode,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--job", help="Specific job id to inspect")
    p.add_argument(
        "--stale",
        type=int,
        default=2,
        help="Threshold in days for flagging stale jobs (default: 2)",
    )
    p.add_argument("--json", action="store_true", help="JSON output")
    args = p.parse_args()

    jobs = load_jobs()
    state = load_state()

    if args.job:
        jobs = [j for j in jobs if j.get("id", "").startswith(args.job)]
        if not jobs:
            print(f"No job matching --job {args.job}", file=sys.stderr)
            sys.exit(1)

    results = [diagnose_job(j, state) for j in jobs]

    if args.json:
        print(json.dumps(results, indent=2))
        return

    # Default: prose output (probe-as-answer style)
    now = datetime.now(timezone.utc)
    print(f"=== Cron State Probe — {now.isoformat()} ===")
    print(f"Total jobs: {len(results)}")

    stale = [r for r in results if r["days_since_run"] and r["days_since_run"] >= args.stale]
    silent = [r for r in results if r["sub_mode"] and "SILENT_STRETCH" in r["sub_mode"]]
    errored = [r for r in results if r["last_status"] == "error"]

    print(f"\nStale jobs (last_run_at > {args.stale}d): {len(stale)}")
    for r in sorted(stale, key=lambda x: -(x["days_since_run"] or 0)):
        print(
            f"  {r['name']:40s} {r['id']} last_ran={r['last_run_at'][:19] if r['last_run_at'] else 'never'} "
            f"({r['days_since_run']}d ago) sub_mode={r['sub_mode'] or 'ok'}"
        )

    print(f"\nSilent-stretch candidates (sub_mode A): {len(silent)}")
    for r in silent:
        print(f"  {r['name']:40s} {r['id']} status={r['last_status']} sub_mode={r['sub_mode']}")

    print(f"\nErrored jobs: {len(errored)}")
    for r in errored[:10]:
        print(f"  {r['name']:40s} {r['id']} status={r['last_status']}")


if __name__ == "__main__":
    main()
