"""Proof for Phase A1: progress_notify streams as ONE editing Telegram message.

Imports the REAL coordinator module (import-safe — daemon loop is under
__main__) and drives progress_notify against a throwaway DB holding one
operator-facing task. Asserts:
  1. first call SENDS and persists a progress_msg_id on the task,
  2. second call EDITS that SAME message (message_id unchanged on Telegram),
  3. a housekeeping (internal-source) task stays SILENT (no id stored).

This sends 2 real Telegram messages (1 send + 1 edit) to the home channel —
that live round-trip IS the proof the edit path resolves in production.
Run directly: /usr/local/bin/python3 test_progress_stream.py
"""
import os, sqlite3, sys, tempfile
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

def mk_conn():
    path = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(TASKS_DDL); conn.commit()
    return conn

def insert(conn, tid, kind, source):
    conn.execute("INSERT INTO tasks(id,kind,source,title,status,created_at) VALUES(?,?,?,?,?,?)",
                 (tid, kind, source, f"A1 proof {tid}", "executing", 0.0))
    conn.commit()
    return conn.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()

def msg_id(conn, tid):
    return conn.execute("SELECT progress_msg_id FROM tasks WHERE id=?", (tid,)).fetchone()[0]

hard = False

# --- operator-facing task streams as one editing message --------------------
conn = mk_conn()
task = insert(conn, "a1op", "project", "project:prospector")
assert C._is_operator_facing(task), "project task must be operator-facing"

C.progress_notify(conn, task, "⚙️ [A1 proof] step 1 — Working on: prospector report")
id1 = msg_id(conn, "a1op")
if id1:
    print(f"PASS  step1 sent + id persisted (message_id={id1})")
else:
    print("FAIL  step1 produced no progress_msg_id (send failed?)"); hard = True

# re-read row so the helper sees the stored id, then edit in place
task = conn.execute("SELECT * FROM tasks WHERE id=?", ("a1op",)).fetchone()
C.progress_notify(conn, task, "✅ [A1 proof] step 2 — Done: prospector report (EDITED IN PLACE)")
id2 = msg_id(conn, "a1op")
if id1 and id2 == id1:
    print(f"PASS  step2 EDITED the same message (message_id stayed {id2})")
elif id1 and id2 != id1:
    print(f"FAIL  step2 made a NEW message ({id1} -> {id2}); edit path not used"); hard = True

# --- housekeeping task is silent --------------------------------------------
conn2 = mk_conn()
hk = insert(conn2, "a1hk", "task", "memory-hygiene")
assert not C._is_operator_facing(hk), "memory-hygiene must be silent"
C.progress_notify(conn2, hk, "should never send")
if msg_id(conn2, "a1hk") is None:
    print("PASS  housekeeping task stayed silent (no message, no id)")
else:
    print("FAIL  housekeeping task sent a progress message"); hard = True

print("ALL GREEN" if not hard else "FAILURES ABOVE")
sys.exit(1 if hard else 0)
