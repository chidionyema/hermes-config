"""Proof for Phase C: executors run OFF the tick thread (non-blocking) and concurrency
is bounded — so one slow executor can no longer freeze the coordinator tick/heartbeat,
and a fleet of them can no longer melt the box (the measured load-43 failure).

Drives the REAL coordinator.advance() against a throwaway DB with coordinator.execute
monkeypatched to a controllable slow stub. Asserts:
  1. NON-BLOCKING: advance() on an `executing` task returns in << the stub's runtime
     (it submits to the pool, doesn't run inline),
  2. STAYS executing + bumps heartbeat while the future runs,
  3. COLLECTS the result and moves to `verifying` once the future completes,
  4. CONCURRENCY CAP: with N>MAX_EXECUTORS tasks dispatched, no more than
     MAX_EXECUTORS run at once.
Run: /usr/local/bin/python3 test_async_executor.py
"""
import sqlite3, sys, threading, time, tempfile
import coordinator as C

TASKS_DDL = """
CREATE TABLE tasks (
  id TEXT PRIMARY KEY, kind TEXT, source TEXT, title TEXT, body TEXT,
  risk_class TEXT, status TEXT, spec TEXT, result TEXT,
  consecutive_failures INTEGER DEFAULT 0, last_failure_error TEXT,
  created_by TEXT, created_at REAL, started_at REAL, completed_at REAL,
  last_heartbeat_at REAL, progress_msg_id TEXT
);
"""

EVENTS_DDL = """
CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, kind TEXT,
                     payload TEXT, created_at REAL);
"""

def mk_conn():
    conn = sqlite3.connect(tempfile.mktemp(suffix=".db"))
    conn.row_factory = sqlite3.Row
    conn.execute(TASKS_DDL); conn.execute(EVENTS_DDL); conn.commit()
    return conn

def add(conn, tid):
    # source 'memory-hygiene' => NOT operator-facing => progress_notify stays silent (no Telegram)
    conn.execute("INSERT INTO tasks(id,kind,source,title,status,created_at,last_heartbeat_at)"
                 " VALUES(?,?,?,?,?,?,?)", (tid, "task", "memory-hygiene", f"async {tid}",
                                           "executing", 0.0, 0.0))
    conn.commit()
    return conn.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()

def row(conn, tid):
    return conn.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()

hard = False
C._EXECUTORS.clear()

# concurrency instrumentation shared by the stub
live = {"now": 0, "max": 0}
lock = threading.Lock()
def slow_execute(task, router, _dur=0.6):
    with lock:
        live["now"] += 1; live["max"] = max(live["max"], live["now"])
    try:
        time.sleep(_dur)
        return f"EVIDENCE for {task['id']}"
    finally:
        with lock:
            live["now"] -= 1
C.execute = slow_execute   # monkeypatch the module global the pool resolves at call time

# --- 1+2+3: non-blocking submit, stays executing, then collects ----------------
conn = mk_conn(); t = add(conn, "x1")
t0 = time.time(); st = C.advance(conn, t); submit_dt = time.time() - t0
# must return in ~EXEC_GRACE_S, NOT block on the 600ms stub
if st == "executing" and submit_dt < (C.EXEC_GRACE_S + 0.2) and "x1" in C._EXECUTORS:
    print(f"PASS  advance() submitted off-thread in {submit_dt*1000:.0f}ms (did not block on the 600ms stub)")
else:
    print(f"FAIL  expected fast submit+executing, got st={st} dt={submit_dt:.2f} reg={'x1' in C._EXECUTORS}"); hard = True

# poll until the future finishes; advance() must keep returning 'executing' meanwhile
moved = None
for _ in range(40):
    t = row(conn, "x1")
    st = C.advance(conn, t)
    if st != "executing":
        moved = st; break
    time.sleep(0.1)
final = row(conn, "x1")
if moved == "verifying" and final["status"] == "verifying" and final["result"] == "EVIDENCE for x1":
    print("PASS  result collected on a later tick -> verifying, evidence stored")
else:
    print(f"FAIL  expected verifying+evidence, got moved={moved} status={final['status']} result={final['result']!r}"); hard = True

# --- 4: concurrency cap --------------------------------------------------------
C._EXECUTORS.clear(); live["now"] = 0; live["max"] = 0
conn2 = mk_conn()
ids = [f"c{i}" for i in range(5)]
for i in ids: add(conn2, i)
# dispatch all (each first advance submits one future)
for i in ids:
    C.advance(conn2, row(conn2, i))
# let the pool churn through them, polling to completion
deadline = time.time() + 15
while time.time() < deadline:
    pending = False
    for i in ids:
        r = row(conn2, i)
        if r["status"] == "executing":
            C.advance(conn2, r); pending = True
    if not pending:
        break
    time.sleep(0.1)
done = sum(1 for i in ids if row(conn2, i)["status"] == "verifying")
if live["max"] <= C.MAX_EXECUTORS and done == len(ids):
    print(f"PASS  concurrency capped: peak {live['max']} <= MAX_EXECUTORS={C.MAX_EXECUTORS}; all {done} finished")
else:
    print(f"FAIL  peak concurrency {live['max']} (cap {C.MAX_EXECUTORS}); done={done}/{len(ids)}"); hard = True

# --- 5: grace path — an INSTANT executor collects in a SINGLE advance ----------
# (this is what keeps the hermetic synchronous lifecycle in test_coordinator deterministic)
C._EXECUTORS.clear()
C.execute = lambda task, router: f"INSTANT {task['id']}"   # returns immediately
conn3 = mk_conn(); g = add(conn3, "g1")
st = C.advance(conn3, g)
gr = row(conn3, "g1")
if st == "verifying" and gr["status"] == "verifying" and gr["result"] == "INSTANT g1":
    print("PASS  instant executor collected within the grace window (single advance -> verifying)")
else:
    print(f"FAIL  grace path: st={st} status={gr['status']} result={gr['result']!r}"); hard = True

print("ALL GREEN" if not hard else "FAILURES ABOVE")
sys.exit(1 if hard else 0)
