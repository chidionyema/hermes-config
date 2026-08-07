#!/usr/bin/env python3
"""Proofs for the RSI authority recency window.

Why this exists: on 2026-08-07 the authority gate declined with prompt_authority
1.2% computed over ALL TIME, where 170 of 174 recorded executor timeouts were the
30s cap fixed the day before and every no-cause fallback predated the exit-1 cause
fix (coordinator.py:1349). RSI was blocked by ghosts.

Every proof builds its own temp DB. Nothing here touches ~/.hermes/coordinator.db.
No LLM calls, no network.
"""
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rsi_outcome_ledger as L  # noqa: E402

DAY = 86400.0
NOW = 1_786_000_000.0  # fixed reference; never the wall clock
FB = "[executor-narrative-fallback"

_checks = 0
_failed = []


def check(name, cond, detail=""):
    global _checks
    _checks += 1
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        _failed.append(name)


def make_db(rows):
    """rows: (age_days, status, result). Returns a temp db path."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    con = sqlite3.connect(path)
    con.execute("create table tasks (id text primary key, title text, status text, "
                "result text, created_at real, completed_at real)")
    for i, (age, status, result) in enumerate(rows):
        ts = NOW - age * DAY
        con.execute("insert into tasks values (?,?,?,?,?,?)",
                    (f"t{i}", f"task {i}", status, result, ts, ts))
    con.commit()
    con.close()
    return path


def timeout(secs=30):
    return f"{FB} (claude: timeout after {secs}s; reasoning via minimax/MiniMax-M3)] narrative"


def ran_but_wrong():
    # executor RAN, did real work, task still failed -> prompt_quality
    return "## Result\n\nDid the work, verification rejected it."


print("PROOF 1 — ghosts stop voting once outside the window")
# 40 old timeouts (a bug fixed long ago) + 10 recent genuine prompt failures.
db = make_db([(30, "done", timeout())] * 40 + [(1, "failed", ran_but_wrong())] * 10)
allt = L.prompt_authority(db)
recent = L.recent_authority(db, window_days=14, now=NOW)
check("all-time authority is crushed by the fixed bug",
      allt["prompt_authority"] < 0.25, f"got {allt['prompt_authority']}")
check("all-time dominant lever is the dead timeout",
      allt["dominant_lever"] == "executor_timeout", f"got {allt['dominant_lever']}")
check("windowed authority sees only the live regime",
      recent["prompt_authority"] == 1.0, f"got {recent['prompt_authority']}")
check("windowed dominant lever is prompt_quality",
      recent["dominant_lever"] == "prompt_quality", f"got {recent['dominant_lever']}")
check("window is reported for the receipt", recent.get("window_days") == 14)
os.unlink(db)

print("PROOF 2 — FALSIFIER: the window must not be a rubber stamp")
# The same shape, but the timeouts are RECENT. Authority must stay low and the
# gate must still block. Without this, an unconditional-pass change passes PROOF 1.
db = make_db([(2, "done", timeout(900))] * 40 + [(1, "failed", ran_but_wrong())] * 2)
recent = L.recent_authority(db, window_days=14, now=NOW)
check("recent timeouts still dominate", recent["dominant_lever"] == "executor_timeout",
      f"got {recent['dominant_lever']}")
check("authority stays below the 20% floor",
      recent["prompt_authority"] < L.MIN_AUTHORITY_SAMPLE / 100 + 0.20,
      f"got {recent['prompt_authority']}")
check("authority is genuinely low", recent["prompt_authority"] < 0.20,
      f"got {recent['prompt_authority']}")
os.unlink(db)

print("PROOF 3 — a handful of rows is noise, not a measurement")
db = make_db([(1, "failed", ran_but_wrong())] * 2)
recent = L.recent_authority(db, window_days=14, now=NOW)
check("2 failures < min sample -> insufficient", recent["sufficient_sample"] is False,
      f"got {recent['sufficient_sample']}")
check("min_sample is reported", recent["min_sample"] == L.MIN_AUTHORITY_SAMPLE)
os.unlink(db)
db = make_db([(1, "failed", ran_but_wrong())] * 9)
recent = L.recent_authority(db, window_days=14, now=NOW)
check("9 failures >= min sample -> sufficient", recent["sufficient_sample"] is True)
os.unlink(db)

print("PROOF 4 — the window is a real filter, not a relabelling")
db = make_db([(30, "done", timeout())] * 40 + [(1, "failed", ran_but_wrong())] * 10)
allt = L.prompt_authority(db)
recent = L.recent_authority(db, window_days=14, now=NOW)
check("all-time counts every row", allt["failures"] == 50, f"got {allt['failures']}")
check("window drops the out-of-range rows", recent["failures"] == 10,
      f"got {recent['failures']}")
check("boundary is exclusive-below, not off by a day",
      L.recent_authority(db, window_days=31, now=NOW)["failures"] == 50)
os.unlink(db)

print("PROOF 5 — no wall clock: `now` is injectable and deterministic")
db = make_db([(10, "failed", ran_but_wrong())] * 6)
a = L.recent_authority(db, window_days=14, now=NOW)
b = L.recent_authority(db, window_days=14, now=NOW)
check("same inputs -> same attribution", a == b)
check("a window that excludes everything yields 0 failures",
      L.recent_authority(db, window_days=1, now=NOW)["failures"] == 0)
os.unlink(db)

print("PROOF 6 — the orchestrator calls the WINDOWED entry point")
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "rsi-orchestrator.py"), encoding="utf-8").read()
check("gate uses recent_authority", "_ledger.recent_authority(COORDINATOR_DB)" in src)
check("gate no longer uses the all-time call",
      "_ledger.prompt_authority(COORDINATOR_DB)" not in src)
check("gate honours the sample floor", 'attrib.get("sufficient_sample", True)' in src)

print(f"\n{_checks - len(_failed)}/{_checks} checks passed")
sys.exit(1 if _failed else 0)
