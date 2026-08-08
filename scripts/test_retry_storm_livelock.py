#!/usr/bin/env python3
"""Proofs for the retry-storm livelock of 2026-08-08.

THE INCIDENT, from the live coordinator.db:
  task 7940a00f98cd ("Signal M7-Live: ship one RED matrix gap") sat in `verifying` with
  consecutive_failures=1102 against MAX_RETRIES=2. Every tick it failed verification with
  "executor could not act (fell back to chat)" — the executor's own result records
  `claude: exit 1: You've hit your monthly spend limit` — and every tick `escalate()`
  raised EscalationWithoutDiagnosis, because nothing had ever written a `diagnosis` event.
  The tick loop re-raised. So for 18 hours:
    * 1,071 identical rejected attempts were written, once a minute;
    * `list_active` is ORDERed by created_at and this was the oldest active task, so no
      younger task advanced — 1,073 `daemon/loop_error` events, four `open` tasks frozen;
    * the founder was told NOTHING, which is the precise outcome the escalation cure
      exists to prevent, produced by the cure itself;
    * the RSI outcome ledger read those 1,071 rows as 1,071 independent failures, which
      dragged 14-day prompt_authority to 15.86% — below the gate's 20% floor, so the
      nightly tuner would have declined rc=3 for a fortnight on one stuck row.

Three fixes, one proof each below, plus the falsifier for each.
"""
import json
import os
import sqlite3
import sys
import tempfile

os.environ["COORD_NO_TELEGRAM"] = "1"          # before importing coordinator, as its own
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # suite does
import coordinator as C            # noqa: E402
import rsi_outcome_ledger as L     # noqa: E402

_checks, _failed = 0, []


def check(name, cond, detail=""):
    global _checks
    _checks += 1
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        _failed.append(name)


def fresh_db():
    conn = C.connect(tempfile.mktemp(suffix=".db"))
    C.init_db(conn)
    return conn


def put_task(conn, tid, status="verifying", fails=0, created=1000.0, result="", title="t"):
    conn.execute(
        "INSERT INTO tasks(id,kind,source,title,body,risk_class,status,result,"
        "consecutive_failures,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (tid, "injected", "project:x", title, "b", "low", status, result, fails, "test", created))
    conn.commit()
    return C.get_task(conn, tid)


FALLBACK = "executor could not act (fell back to chat) — no real work performed"
SPEND = "[executor-narrative-fallback (claude: exit 1: You've hit your monthly spend limit)]"


# ── 1. The ledger: a storm is ONE failure observed N times ────────────────────────
print("PROOF 1 — a single task's retry storm cannot outvote the estate")
storm = [{"task_id": "hot", "ts": float(i), "reason": FALLBACK, "lever": "executor_fallback"}
         for i in range(1000)]
real = [{"task_id": f"t{i}", "ts": 2000.0 + i, "reason": "failure condition still present",
         "lever": "prompt_quality_unfixed"} for i in range(10)]

kept, dropped = L.collapse_retry_storms(storm + real, cap=3)
check("the storm keeps exactly `cap` votes", sum(1 for k in kept if k["task_id"] == "hot") == 3,
      f"got {sum(1 for k in kept if k['task_id'] == 'hot')}")
check("it is not erased — the lever still votes",
      any(k["lever"] == "executor_fallback" for k in kept))
check("every distinct task survives untouched",
      sum(1 for k in kept if k["task_id"] != "hot") == 10)
check("the earliest attempts are the ones kept",
      [k["ts"] for k in kept if k["task_id"] == "hot"] == [0.0, 1.0, 2.0])
check("drops are attributed to the task that caused them", dropped.get(("hot", "executor_fallback")) == 997,
      f"got {dropped}")

a = L.attempt_attribute(storm + real)
check("attribution collapses automatically", a["failures"] == 13, f"got {a['failures']}")
check("the raw count is still reported, never hidden", a["raw_failures"] == 1010)
check("the collapse names its own effect", a["storm_dropped"] == 997 and a["storm_tasks"] == ["hot"])
check("authority reflects the estate: 10 of 13", a["prompt_authority"] == round(10 / 13, 4),
      f"got {a['prompt_authority']}")

# FALSIFIER: without the collapse this same corpus reads as a blocked gate.
raw = L.attempt_attribute(storm + real, storm_cap=0)
check("FALSIFIER — uncollapsed, the storm buries the signal at 1.0%",
      raw["prompt_authority"] == round(10 / 1010, 4), f"got {raw['prompt_authority']}")
check("FALSIFIER — and that reading is below the 20% floor the gate uses",
      raw["prompt_authority"] < 0.20 <= a["prompt_authority"])
check("cap<=0 means 'give me the raw corpus'", raw["failures"] == 1010)


# ── 2. The retry ceiling always produces a diagnosis ──────────────────────────────
print("\nPROOF 2 — a task at the retry ceiling gets a diagnosis derived from its evidence")
conn = fresh_db()
put_task(conn, "stuck", fails=1102, result=SPEND)
check("precondition: nothing investigated it", not C.has_event(conn, "stuck", "diagnosis"))
check("_ensure_diagnosis writes one", C._ensure_diagnosis(conn, "stuck", FALLBACK) is True)
row = conn.execute("select payload from events where task_id='stuck' and kind='diagnosis'").fetchone()
d = json.loads(row[0])
check("it is STAMPED auto, never confusable with an investigation", d["auto"] is True)
check("it names the actuator from the ledger's own classifier",
      d["lever"] == "executor_fallback", f"got {d['lever']}")
check("it carries the executor's own error, not a placeholder",
      "monthly spend limit" in d["evidence"], f"got {d['evidence'][:80]!r}")
check("it carries the verifier's recorded reason", "fell back to chat" in d["reason"])

# The point of the diagnosis: escalate() now succeeds, so the task LEAVES the active set.
msgs = []
C.escalate(conn, C.get_task(conn, "stuck"), "failed verification 1102×", msgs.append)
check("escalate no longer raises → task is terminal",
      C.get_task(conn, "stuck")["status"] in C.TERMINAL,
      f"got {C.get_task(conn, 'stuck')['status']}")

# FALSIFIER: it must NEVER overwrite a real, investigated diagnosis.
conn2 = fresh_db()
put_task(conn2, "investigated", fails=9, result=SPEND)
C.add_event(conn2, "investigated", "diagnosis", json.dumps({"root_cause": "a human looked"}))
check("FALSIFIER — an existing diagnosis is left alone",
      C._ensure_diagnosis(conn2, "investigated", FALLBACK) is False)
kept_d = json.loads(conn2.execute(
    "select payload from events where task_id='investigated' and kind='diagnosis'").fetchone()[0])
check("FALSIFIER — and its content is untouched", kept_d.get("root_cause") == "a human looked")
check("FALSIFIER — exactly one diagnosis event exists", conn2.execute(
    "select count(*) from events where task_id='investigated' and kind='diagnosis'").fetchone()[0] == 1)


# ── 3. One undiagnosable task must not stop the estate ────────────────────────────
print("\nPROOF 3 — the propulsion tick parks an undiagnosable task instead of aborting")
conn3 = fresh_db()
put_task(conn3, "offender", status="verifying", fails=1102, created=1.0, result=SPEND)
put_task(conn3, "younger", status="open", fails=0, created=9999.0)

# Sampled BEFORE the tick, on purpose: afterwards the offender is parked and out of the
# active set, so a post-hoc query cannot show the ordering that caused the starvation.
order_before = [r[0] for r in conn3.execute(
    "select id from tasks where status in ('open','diagnosed','executing','verifying',"
    "'awaiting_approval') order by created_at")]

seen = []
_real_advance = C.advance


def _advance(conn, task, *a, **k):
    seen.append(task["id"])
    if task["id"] == "offender":
        raise C.EscalationWithoutDiagnosis("task offender has no diagnosis")
    return "diagnosed"


C.advance = _advance
notes = []
try:
    C.tick(conn3, router=lambda *a, **k: "{}", notifier=notes.append)
finally:
    C.advance = _real_advance

check("the tick did not abort — the younger task was still reached", "younger" in seen,
      f"reached {seen}")
check("the offender left the active set (blocked is TERMINAL)",
      C.get_task(conn3, "offender")["status"] == "blocked",
      f"got {C.get_task(conn3, 'offender')['status']}")
check("the refusal is recorded on the task",
      C.has_event(conn3, "offender", "error"))
check("the operator is told it was parked", any("Parked" in m for m in notes), f"got {notes}")
check("the cure still holds — nothing was escalated without a diagnosis",
      not C.has_event(conn3, "offender", "escalate"))

# FALSIFIER: the offender is ordered FIRST (created_at 1.0), so under the old re-raise it
# would have starved `younger` exactly as production did. Without this ordering the whole
# starvation claim is unfounded, so it is pinned rather than assumed.
check("FALSIFIER — the raiser was the OLDEST active task, i.e. first in the loop",
      order_before == ["offender", "younger"], f"order was {order_before}")
check("FALSIFIER — and the younger task was reached only after it raised",
      seen.index("offender") < seen.index("younger"), f"seen {seen}")

print(f"\n{_checks - len(_failed)}/{_checks} checks passed")
sys.exit(1 if _failed else 0)
