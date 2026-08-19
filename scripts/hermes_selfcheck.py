#!/usr/bin/env python3
"""One command that answers "is Hermes actually healthy", by invariant rather than by liveness.

Why this exists. On 2026-08-19 two Hermes defects were found by a human reading logs by hand.
Both had been live for weeks. The estate already had 25 health, watchdog and audit scripts and
16 launchd jobs, and not one of them noticed either, because every one of them asks "is the
process up" and neither defect stopped a process:

  * `sysctl` is in /usr/sbin, which a launchd job does not get on PATH. The idle-learning load
    gate read an empty load and a CPU count of 1, so it never deferred at any host load. The
    only trace was `sysctl: command not found` in a different job's stderr, 410 times.
  * 236 tasks sat in status `failed`, which was in neither ACTIVE nor TERMINAL, so the tick
    could not see them and no rollup counted them. Invisible debt.

A watchdog that only checks liveness cannot see either. So this checks CORRECTNESS invariants,
each one written from a defect that actually happened, and each one cheap enough to run hourly.

Read-only. Exit 0 when every invariant holds, 1 when any fails, 2 on its own error — a check
that cannot run must not read as a pass, which is the whole class of bug it is here to catch.

  hermes_selfcheck.py            # the table
  hermes_selfcheck.py --json     # for the ops console
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "coordinator.db"
LOGS = ROOT / "logs"

ACTIVE = ("open", "diagnosed", "executing", "verifying", "awaiting_approval")
TERMINAL = ("done", "escalated", "blocked", "failed", "cancelled")

# Signatures of a tool that was not found. Every one of these means a command silently did
# nothing, and the caller almost always swallowed it.
MISSING_TOOL = re.compile(r"(command not found|: not found$|No such file or directory)", re.M)

# An executor that fell back to a brain with no tool runtime cannot have done remediation work.
FALLBACK_MARKERS = ("[executor-narrative-fallback", "[executor-unavailable-fallback",
                    "[agentic-exec-fallback")

# The silent-acceptance guard landed in coordinator.py at this moment (~/.hermes 3861d76,
# 2026-08-18 23:49:16 +0100). Closes from before it are the population the guard exists to
# end; counting them would grade the disease, not the cure. This is the floor for that check
# and it is the same number task #57 grades against.
GUARD_LANDED = 1787093356.0

RESULTS: list[dict] = []


def check(name: str, why: str):
    """Register one invariant. The function returns (ok, detail)."""
    def deco(fn):
        try:
            ok, detail = fn()
        except Exception as exc:                      # a check that crashes is a FAIL, not a pass
            ok, detail = False, f"the check itself failed: {exc!r}"
        RESULTS.append({"name": name, "ok": bool(ok), "detail": detail, "why": why})
        return fn
    return deco


def _rows(sql: str, args=()) -> list[tuple]:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


@check("no tool went missing", "a bare /usr/sbin tool under launchd fails silently and the "
       "caller's fallback usually points the wrong way")
def _missing_tools():
    cutoff = time.time() - 24 * 3600
    hits = []
    for log in sorted(LOGS.glob("*.log")):
        if "err" not in log.name and "error" not in log.name:
            continue
        if log.stat().st_mtime < cutoff:
            continue
        tail = log.read_text(encoding="utf-8", errors="replace")[-200_000:]
        found = MISSING_TOOL.findall(tail)
        if found:
            hits.append(f"{log.name} x{len(found)}")
    return not hits, ("clean across the last 24h of job stderr" if not hits
                      else "a command was not found in: " + ", ".join(hits))


@check("every task status is reachable", "a status in neither ACTIVE nor TERMINAL is worked by "
       "nothing and counted by nothing")
def _reachable_status():
    known = set(ACTIVE) | set(TERMINAL)
    stray = [(s, n) for s, n in _rows("select status, count(*) from tasks group by status")
             if s not in known]
    return not stray, ("all statuses are in ACTIVE or TERMINAL" if not stray
                       else "stranded: " + ", ".join(f"{s}={n}" for s, n in stray))


@check("the coordinator is making progress", "running is not the same as working — the tick can "
       "be up and moving nothing")
def _progress():
    (moved,) = _rows("select count(*) from tasks where coalesce(completed_at, started_at, "
                     "created_at) > ?", (time.time() - 6 * 3600,))[0:1][0], 
    moved = moved if isinstance(moved, int) else moved[0]
    (backlog,) = _rows("select count(*) from tasks where status in (%s)"
                       % ",".join("?" * len(ACTIVE)), ACTIVE)[0]
    if backlog == 0:
        return True, "nothing is queued, so no progress is owed"
    return moved > 0, (f"{moved} task(s) moved in the last 6h against a backlog of {backlog}"
                       if moved else f"{backlog} task(s) queued and NOTHING moved in 6h")


@check("the coordinator is observable", "a process that writes no log can only be debugged by "
       "reading its database by hand, which is how both 2026-08-19 defects survived for weeks")
def _observable():
    log = LOGS / "coordinator.log"
    if not log.exists():
        return False, "logs/coordinator.log does not exist"
    size = log.stat().st_size
    age_d = (time.time() - log.stat().st_mtime) / 86400
    return size > 0 and age_d < 2, (
        f"coordinator.log is {size} bytes, last written {age_d:.1f} days ago — the coordinator "
        f"has no logging at all" if size == 0 or age_d >= 2 else f"{size} bytes, fresh")


@check("no task closed on evidence that it did nothing", "208 tasks closed as done on an "
       "acceptance test that exited 0 and printed nothing while the executor had no tools")
def _no_false_closes():
    since = max(GUARD_LANDED, time.time() - 7 * 86400)
    rows = _rows("select id, title, result from tasks where status='done' and "
                 "coalesce(completed_at,0) > ?", (since,))
    bad = [f"{i[:8]} {(t or '')[:40]}" for i, t, r in rows
           if r and any(m in r for m in FALLBACK_MARKERS)]
    return not bad, (f"{len(rows)} task(s) closed since the guard landed, none on fallback "
                     f"evidence" if not bad
                     else f"{len(bad)} closed on fallback evidence: " + "; ".join(bad[:5]))


@check("every hermes job exited cleanly", "a job that dies on every run still shows as loaded")
def _jobs_clean():
    out = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=20).stdout
    bad = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 3 or not parts[2].startswith("ai.hermes."):
            continue
        pid, status, label = parts[0], parts[1], parts[2]
        # A job that is running RIGHT NOW recovered; its last exit is history, not an alarm.
        # ai.hermes.gateway reports -9 by design — `gateway run --replace` SIGKILLs the
        # instance it replaces — and alerting on that is the noise, not the signal.
        if pid != "-":
            continue
        # `-15` and `-2` are a deliberate stop (launchctl kickstart -k, a reload, a logout).
        # `-9` is a kill and `>0` is a crash; those are the ones worth waking someone for.
        if status in ("0", "-", "-15", "-2", "-3"):
            continue
        bad.append(f"{label} last exit {status}")
    return not bad, ("all ai.hermes.* jobs last exited 0" if not bad else "; ".join(bad))


STATE = ROOT / "state" / "selfcheck.json"


def _alert_on_change(failed: list[dict]) -> None:
    """Page only when the failure SET changes. Repeating an unfixed failure every hour is the
    noise the founder means by "annoying alerts instead of a useful agent": it trains you to
    ignore the channel, so the one new failure arrives in a stream you have stopped reading.

    A new failure pages once, with the reason and the command that reproduces it. A failure
    that clears pages once, so a fix is visible without asking. Steady state is silence."""
    now = sorted(r["name"] for r in failed)
    was: list[str] = []
    try:
        was = sorted(json.loads(STATE.read_text()).get("failing", []))
    except Exception:
        pass
    if now == was:
        return
    appeared = [n for n in now if n not in was]
    cleared = [n for n in was if n not in now]
    lines = ["*Hermes self-check changed*"]
    for n in appeared:
        r = next(x for x in failed if x["name"] == n)
        lines.append(f"NEW FAIL: {n} — {r['detail']}")
    for n in cleared:
        lines.append(f"cleared: {n}")
    lines.append("`python3 ~/.hermes/scripts/hermes_selfcheck.py`")
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        import estate_alert
        estate_alert.send_operator_alert("\n".join(lines), debounce_key="hermes-selfcheck")
    except Exception as exc:
        print(f"(alert not sent: {exc!r})", file=sys.stderr)


def main() -> int:
    failed = [r for r in RESULTS if not r["ok"]]
    if "--alert" in sys.argv:
        _alert_on_change(failed)
    if "--alert" in sys.argv or "--json" in sys.argv:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps({
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "ok": not failed, "failing": [r["name"] for r in failed], "checks": RESULTS}, indent=2))
    if "--json" in sys.argv:
        print(json.dumps({
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "ok": not failed, "failed": len(failed), "checks": RESULTS}, indent=2))
        return 1 if failed else 0
    width = max(len(r["name"]) for r in RESULTS)
    for r in RESULTS:
        print(f"{'PASS' if r['ok'] else 'FAIL'}  {r['name']:<{width}}  {r['detail']}")
    if failed:
        print()
        for r in failed:
            print(f"  {r['name']}: {r['why']}")
        print(f"\n{len(failed)} of {len(RESULTS)} invariants FAILED.")
    else:
        print(f"\nall {len(RESULTS)} invariants hold.")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"hermes_selfcheck could not run: {exc!r}", file=sys.stderr)
        sys.exit(2)
