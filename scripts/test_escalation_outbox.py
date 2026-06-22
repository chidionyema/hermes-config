"""Integration test: the LIVE coordinator.escalate() now writes the transactional
outbox and never loses a founder escalation. Run: python3 test_escalation_outbox.py

Proves, against the real coordinator module (imported, not mocked):
  A) send succeeds      -> outbox row exists AND is marked dispatched (no retry needed)
  B) send fails (outage)-> outbox row persists PENDING; drain_outbox redelivers exactly once
  C) decision buttons OK-> row dispatched
Each asserts the live send was actually attempted (the existing path is intact).
"""
import os, sqlite3, tempfile, sys
import coordinator as C
import outbox

TASKS_DDL = """
CREATE TABLE tasks (id TEXT PRIMARY KEY, kind TEXT, source TEXT, title TEXT,
                    spec TEXT, status TEXT, last_heartbeat_at REAL);
CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, kind TEXT,
                     payload TEXT, created_at REAL);
"""


def fresh():
    fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd)
    conn = sqlite3.connect(path); conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(TASKS_DDL)
    outbox.ensure_schema(conn)
    conn.execute("INSERT INTO tasks(id,kind,source,title,spec,status) "
                 "VALUES('T1','injected','telegram','Decide the rail','{}','diagnosed')")
    conn.execute("INSERT INTO events(task_id,kind,payload,created_at) VALUES('T1','diagnosis','{}',1.0)")
    conn.commit()
    return conn, path


def task(conn):
    return conn.execute("SELECT * FROM tasks WHERE id='T1'").fetchone()


def outbox_rows(conn):
    return conn.execute("SELECT event_type,payload_message,dispatch_status FROM transactional_outbox").fetchall()


def test_send_success_marks_dispatched():
    conn, path = fresh()
    calls = []
    C.send_telegram_buttons = lambda msg, tid: (_ for _ in ()).throw(AssertionError("buttons used in non-decision"))
    notifier = lambda m: (calls.append(m) or True)          # send SUCCEEDS
    C.escalate(conn, task(conn), "needs human", notifier, decision=False)
    rows = outbox_rows(conn)
    assert len(calls) == 1, "live notifier was not called — existing path broken"
    assert len(rows) == 1 and rows[0]["dispatch_status"] == 1, f"not marked dispatched: {list(rows[0])}"
    conn.close(); os.unlink(path)
    print("PASS  send-success: outbox row written AND marked dispatched; live send still fired")


def test_send_failure_persists_then_redelivers():
    conn, path = fresh()
    C.send_telegram_buttons = lambda msg, tid: False
    notifier_down = lambda m: False                          # gateway DOWN
    C.escalate(conn, task(conn), "needs human", notifier_down, decision=False)
    rows = outbox_rows(conn)
    assert len(rows) == 1 and rows[0]["dispatch_status"] == 0, f"should be pending: {list(rows[0])}"

    # gateway recovers: drain redelivers exactly once
    got = []
    n = C.drain_outbox(conn, lambda m: (got.append(m) or True))
    assert n == 1, f"redelivered {n}, expected 1"
    assert outbox_rows(conn)[0]["dispatch_status"] == 1, "not marked after redelivery"
    assert C.drain_outbox(conn, lambda m: (got.append(m) or True)) == 0, "duplicate redelivery"
    conn.close(); os.unlink(path)
    print("PASS  send-failure: row persists PENDING through outage, redelivers exactly once on recovery")


def test_decision_buttons_path():
    conn, path = fresh()
    used = []
    C.send_telegram_buttons = lambda msg, tid: (used.append(tid) or True)
    notifier = lambda m: (_ for _ in ()).throw(AssertionError("fallback used though buttons succeeded"))
    C.escalate(conn, task(conn), "approve rail?", notifier, decision=True)
    rows = outbox_rows(conn)
    assert used == ["T1"], "decision buttons not used"
    assert rows[0]["dispatch_status"] == 1, "decision not marked dispatched"
    conn.close(); os.unlink(path)
    print("PASS  decision: buttons path delivers and marks the outbox dispatched")


if __name__ == "__main__":
    try:
        test_send_success_marks_dispatched()
        test_send_failure_persists_then_redelivers()
        test_decision_buttons_path()
    except AssertionError as e:
        print("FAIL ", e); sys.exit(1)
    print("ALL GREEN")
