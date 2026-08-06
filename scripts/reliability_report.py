#!/usr/bin/env python3
"""reliability_report — the estate's single "is anything actually broken?" alarm.

Composes three signals that each previously had no consumer:

  1. capability_audit  — what the estate PRODUCED (DARK / BROKEN / UNPROVEN)
  2. latch expiry      — latches held past their declared window
  3. missed_runs.jsonl — scheduled runs the grace window DROPPED

(3) is the one that had nowhere to go. cron/jobs.py::_record_missed_run has been
writing every skipped schedule to logs/alerts/missed_runs.jsonl, and a grep across
the whole estate on 2026-08-06 found zero readers — the same dead end as
queue/pending-digest.json, which is what left the alert chain silent for 46 days.
A detector whose output nobody reads is not a detector.

Output discipline: every alarm goes through alarm_gate, so a persisting fault is
stated once, re-stated once a day, and announced when it clears — never repeated
every hour. See alarm_gate.py for why repetition is fatal to an alarm.

Exit codes (they matter — cron/scheduler.py:1409 delivers on non-zero):
  0  nothing to say, or a recovery notice on stdout
  1  something is wrong and the founder is being told now
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import capability_audit as ca  # noqa: E402
from alarm_gate import decide  # noqa: E402

HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
MISSED = HOME / "logs" / "alerts" / "missed_runs.jsonl"
STATUS = HOME / "state" / "reliability_status.json"

# A missed run older than this is history, not news. Slightly over a day so a
# daily job's single miss is still reported on the following hourly pass.
MISSED_WINDOW_S = 26 * 3600


def recent_missed(now: float, window_s: float = MISSED_WINDOW_S) -> list[dict]:
    """Skipped (not merely late) scheduled runs inside the window, newest first.

    `ran_late` means catch_up saved it — the work happened, so it is not an alarm.
    `skipped` means the run was dropped and will not be retried until the next
    scheduled occurrence. That is silent lost work and it is what we report.
    """
    out: list[dict] = []
    try:
        with open(MISSED) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("action") != "skipped":
                    continue
                try:
                    at = rec.get("at")
                    ts = time.mktime(time.strptime(at[:19], "%Y-%m-%dT%H:%M:%S"))
                except (TypeError, ValueError):
                    continue
                if now - ts <= window_s:
                    rec["_ts"] = ts
                    out.append(rec)
    except OSError:
        return []
    return sorted(out, key=lambda r: r["_ts"], reverse=True)


def collect(now: float) -> tuple[list[tuple[str, str, str]], dict]:
    """Return (failing, raw) where failing is a list of (kind, id, detail)."""
    with open(ca.REGISTRY) as fh:
        reg = json.load(fh)

    caps = ca.audit_capabilities(reg, now)
    latches = ca.audit_latches(reg, now)
    faults = ca.audit_job_integrity()
    missed = recent_missed(now)

    failing: list[tuple[str, str, str]] = []
    for c in caps:
        if c["verdict"] in ca.FAIL_VERDICTS:
            failing.append(("capability", str(c["id"]), f"{c['verdict']}: {c['detail']}"))
    for l in latches:
        if l["verdict"] in ca.FAIL_VERDICTS:
            names = ", ".join(n for n, _ in l["breached"]) or l.get("detail", "")
            failing.append(("latch", str(l["id"]), f"{l['verdict']}: {names}"))
    for f in faults:
        failing.append(("job", str(f["job"]), f"UNRUNNABLE: {f['fault']}"))
    # Group missed runs by job so six skips of one job is one line, not six.
    by_job: dict[str, int] = {}
    for m in missed:
        by_job[str(m.get("job"))] = by_job.get(str(m.get("job")), 0) + 1
    for job, n in sorted(by_job.items()):
        failing.append(("missed", job, f"SKIPPED: {n} scheduled run(s) dropped in 26h"))

    raw = {
        "generated_at": now,
        "capabilities": caps,
        "latches": latches,
        "job_faults": faults,
        "missed_runs_26h": by_job,
    }
    return failing, raw


def fingerprint(failing: list[tuple[str, str, str]]) -> str:
    """Digest the failing IDENTITIES, not their details.

    Detail text carries ages ("held 3.2d") that change every run; including it
    would make every fingerprint unique and defeat suppression entirely — the
    alarm would look gated while still firing hourly.
    """
    if not failing:
        return ""
    body = "\n".join(sorted(f"{k}:{i}:{d.split(':', 1)[0]}" for k, i, d in failing))
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def render(failing: list[tuple[str, str, str]], decision: str) -> str:
    header = {
        "REPORT": "RELIABILITY: NOT PROVEN — state changed",
        "REASSERT": "RELIABILITY: still not proven (daily re-assert)",
    }.get(decision, "RELIABILITY")
    lines = [header, ""]
    for kind, ident, detail in failing:
        lines.append(f"  [{kind}] {ident} — {detail}")
    lines.append("")
    lines.append("Full detail: python3 ~/.hermes/scripts/capability_audit.py")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--reassert-after", type=float, default=86400.0)
    ap.add_argument("--key", default="reliability")
    ap.add_argument("--force", action="store_true",
                    help="ignore the gate and print current state (for humans)")
    args = ap.parse_args()

    now = time.time()
    failing, raw = collect(now)

    # The status file is written on EVERY run, gated or not, so anything that
    # wants health on demand reads current truth rather than the last time we
    # happened to speak.
    try:
        STATUS.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATUS.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({**raw, "failing": failing}, fh, indent=2, default=str)
        os.replace(tmp, STATUS)
    except OSError:
        pass

    fp = fingerprint(failing)
    if args.force:
        print(render(failing, "REPORT") if failing else "RELIABILITY: all proven")
        return 1 if failing else 0

    decision = decide(args.key, fp, args.reassert_after, now=now)

    if decision in {"REPORT", "REASSERT"}:
        print(render(failing, decision))
        # Exit 0, not 1 — the print above is what delivers the alarm. A non-empty
        # stdout on a successful no_agent run is already sent verbatim
        # (scheduler.py, the `doc = ...; return True, doc, output, None` branch),
        # which is the same path RECOVERED below has always used.
        #
        # Exiting 1 delivered the SAME text a second way, as an "error alert"
        # wrapped in "Script exited with code 1" (scheduler.py:1068-1074), and —
        # the part that actually hurt — booked the job as last_status="error"
        # in cron/jobs.json. ops-monitor then re-reported it from that record
        # every ~31 min forever ("1 cron jobs failing: reliability-watchdog",
        # logs/ops-monitor.jsonl), a repeat the alarm_gate fingerprint cannot
        # suppress because it is emitted by a different process reading state,
        # not by this alarm. Repetition is what gets an alarm muted — the exact
        # failure documented in reliability-watchdog.sh:33-40.
        #
        # A watchdog reporting a fault is a watchdog WORKING. "Something is
        # broken" is this script's output, never its own health.
        return 0
    if decision == "RECOVERED":
        # Deliberately exit 0: this is good news, not a failure. Non-empty stdout
        # on a successful no_agent run is delivered verbatim (scheduler.py:1499).
        print("✅ RELIABILITY: recovered — every capability proven, no latch breached.")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
