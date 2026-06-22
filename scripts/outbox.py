"""Transactional outbox for coordinator escalations (spec §7 Phase 2, integrated
against the LIVE coordinator.db schema — NOT the spec's hypothetical loop_tasks).

Verified facts this module is built on (coordinator.db, 2026-06-22):
  - the real task table is `tasks`, primary key `tasks.id` (PRAGMA table_info(tasks)).
  - there is no `loop_tasks` table; introducing one would duplicate the existing
    lifecycle columns (status/consecutive_failures/...), so the outbox FKs `tasks(id)`.

Invariants proven by test_outbox.py:
  - enqueue() runs INSIDE the caller's transaction, so the task state change and the
    outbox row commit together or roll back together (no half-states).
  - with the consumer (gateway) down, the queued event PERSISTS on disk (no loss).
  - drain() marks an event dispatched ONLY after dispatch() returns; a dispatch that
    raises stops the drain and leaves rows pending for retry (at-least-once, no loss).
  - a delivered event is not re-delivered (second drain == 0 on the happy path).

ensure_schema() is additive (CREATE TABLE IF NOT EXISTS) — the Expand step of the
§2.3 migration. It never alters or drops `tasks`.
"""
import sqlite3

OUTBOX_DDL = """
CREATE TABLE IF NOT EXISTS transactional_outbox (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK(event_type IN ('DONE','REJECTED','ESCALATED','BLOCKED','ABANDONED')),
    payload_message TEXT NOT NULL,
    dispatch_status INTEGER DEFAULT 0 CHECK(dispatch_status IN (0,1)),
    created_at REAL NOT NULL,
    FOREIGN KEY(task_id) REFERENCES tasks(id)
);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Additive: create the outbox table if absent. Does not touch `tasks`."""
    conn.execute(OUTBOX_DDL)
    conn.commit()


def enqueue(conn: sqlite3.Connection, task_id: str, event_type: str,
            payload: str, now: float) -> None:
    """Insert an outbox event using the caller's open transaction (no commit here).
    The caller commits the task state change and this row together, so a crash cannot
    persist one without the other."""
    conn.execute(
        "INSERT INTO transactional_outbox(task_id,event_type,payload_message,dispatch_status,created_at)"
        " VALUES(?,?,?,0,?)",
        (task_id, event_type, payload, now),
    )


def pending(conn: sqlite3.Connection):
    return conn.execute(
        "SELECT event_id,task_id,event_type,payload_message FROM transactional_outbox"
        " WHERE dispatch_status=0 ORDER BY event_id"
    ).fetchall()


def drain(conn: sqlite3.Connection, dispatch) -> int:
    """Deliver pending events in order. Mark an event dispatched ONLY after dispatch()
    returns. If dispatch() raises (gateway down), stop and leave that row + the rest
    pending — the next drain retries. Returns the count delivered this call."""
    delivered = 0
    for row in pending(conn):
        event_id = row[0]
        try:
            dispatch(row)
        except Exception:
            break  # row stays pending (status 0); redelivered next drain
        with conn:
            conn.execute(
                "UPDATE transactional_outbox SET dispatch_status=1 WHERE event_id=?",
                (event_id,),
            )
        delivered += 1
    return delivered
