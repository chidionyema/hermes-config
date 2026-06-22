"""§7 Phase 2 sabotage test for outbox.py, run against a tasks-table schema that
mirrors the live coordinator.db. Run: python3 test_outbox.py

Scenario: gateway is down, an ESCALATED state change fires. Required: the state change
verifies on disk, the event is queued, nothing is lost, and it dispatches on recovery.
Plus an atomicity test (rollback leaves neither task-state nor event) and a TEETH test
(a buggy mark-before-dispatch drain MUST lose the event).
"""
import os, sqlite3, tempfile, sys
import outbox

NOW = 1_700_000_000.0

# minimal mirror of the live `tasks` table (id PK + status), enough for the FK + flow
TASKS_DDL = """
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    status TEXT,
    last_heartbeat_at REAL
);
"""


def fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(TASKS_DDL)
    outbox.ensure_schema(conn)
    conn.execute("INSERT INTO tasks(id,status,last_heartbeat_at) VALUES('T1','executing',?)", (NOW,))
    conn.commit()
    return conn, path


def reopen(path):
    c = sqlite3.connect(path); c.execute("PRAGMA foreign_keys=ON"); return c


def escalate_atomic(conn, task_id, payload, now, fail_after=False):
    """Mirror of what coordinator.escalate() will do: set status + enqueue in ONE txn."""
    with conn:
        conn.execute("UPDATE tasks SET status='escalated', last_heartbeat_at=? WHERE id=?", (now, task_id))
        outbox.enqueue(conn, task_id, "ESCALATED", payload, now)
        if fail_after:
            raise RuntimeError("crash mid-transaction")


def test_atomicity_rollback():
    conn, path = fresh_db()
    try:
        escalate_atomic(conn, "T1", "p", NOW, fail_after=True)
    except RuntimeError:
        pass
    disk = reopen(path)
    status = disk.execute("SELECT status FROM tasks WHERE id='T1'").fetchone()[0]
    n = disk.execute("SELECT COUNT(*) FROM transactional_outbox").fetchone()[0]
    assert status == "executing", f"status changed despite rollback: {status!r}"
    assert n == 0, f"event leaked despite rollback: {n}"
    conn.close(); os.unlink(path)
    print("PASS  atomicity: a crash mid-escalation rolls back BOTH status and event")


def test_durability_through_gateway_outage():
    conn, path = fresh_db()
    escalate_atomic(conn, "T1", "needs founder decision", NOW)

    disk = reopen(path)
    assert disk.execute("SELECT status FROM tasks WHERE id='T1'").fetchone()[0] == "escalated", "state not on disk"
    assert len(outbox.pending(conn)) == 1, "event not queued"

    def gateway_down(_row):
        raise ConnectionError("gateway offline")
    assert outbox.drain(conn, gateway_down) == 0, "delivered to a down gateway"
    assert len(outbox.pending(conn)) == 1, "event lost while gateway down"

    got = []
    assert outbox.drain(conn, lambda r: got.append(r[2])) == 1, "recovery did not deliver"
    assert got == ["ESCALATED"], f"wrong event delivered: {got}"
    assert outbox.drain(conn, lambda r: got.append(r[2])) == 0, "duplicate delivery"
    conn.close(); os.unlink(path)
    print("PASS  durability: state on disk, 0 lost while down, 1 on recovery, 0 duplicate")


def test_teeth_buggy_drain_loses_event():
    conn, path = fresh_db()
    escalate_atomic(conn, "T1", "x", NOW)

    def buggy_drain(c, dispatch):
        for row in outbox.pending(c):
            with c:  # BUG: mark dispatched BEFORE delivering
                c.execute("UPDATE transactional_outbox SET dispatch_status=1 WHERE event_id=?", (row[0],))
            dispatch(row)

    try:
        buggy_drain(conn, lambda _r: (_ for _ in ()).throw(ConnectionError("down")))
    except ConnectionError:
        pass
    assert len(outbox.pending(conn)) == 0, "TEETH FAILURE: buggy drain kept the event — test proves nothing"
    conn.close(); os.unlink(path)
    print("PASS  teeth: buggy mark-before-dispatch loses the event when consumer is down (as it must)")


if __name__ == "__main__":
    try:
        test_atomicity_rollback()
        test_durability_through_gateway_outage()
        test_teeth_buggy_drain_loses_event()
    except AssertionError as e:
        print("FAIL ", e); sys.exit(1)
    print("ALL GREEN")
