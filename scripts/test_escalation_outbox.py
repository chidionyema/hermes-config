"""Integration test: the LIVE coordinator.escalate() writes the transactional outbox and
never loses a founder escalation. Run: python3 test_escalation_outbox.py

Proves, against the real coordinator module (imported, not mocked):
  A) send succeeds       -> outbox row exists AND is marked dispatched (no retry needed)
  B) send fails (outage) -> outbox row persists PENDING; drain_outbox redelivers exactly once
  C) a DECISION keeps its ✅ Approve / ❌ Cancel keyboard
  D) a re-escalation EDITS the existing message instead of sending a second one
  E) a DB without the dedup columns still delivers

EVERY send path must be faked in EVERY test. `_hermes_send_capture` shells out to
`hermes send --to telegram`, so an unfaked one does not fail — it delivers a real message to
the founder's phone and then the assertion on the fake notifier fails, which reads like a
logic bug. This suite sent live escalations until the fakes below covered the capture paths.
"""
import os, sqlite3, tempfile, sys
import coordinator as C
import outbox

TASKS_DDL = """
CREATE TABLE tasks (id TEXT PRIMARY KEY, kind TEXT, source TEXT, title TEXT,
                    spec TEXT, status TEXT, last_heartbeat_at REAL,
                    escalation_msg_id TEXT, escalation_count INTEGER DEFAULT 0);
CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, kind TEXT,
                     payload TEXT, created_at REAL);
"""

# The same schema minus the additive migration, for the degrade case.
LEGACY_DDL = TASKS_DDL.replace(
    ",\n                    escalation_msg_id TEXT, escalation_count INTEGER DEFAULT 0", "")


def fresh(ddl=TASKS_DDL):
    fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd)
    conn = sqlite3.connect(path); conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(ddl)
    outbox.ensure_schema(conn)
    conn.execute("INSERT INTO tasks(id,kind,source,title,spec,status) "
                 "VALUES('T1','injected','telegram','Decide the rail','{}','diagnosed')")
    conn.execute("INSERT INTO events(task_id,kind,payload,created_at) VALUES('T1','diagnosis','{}',1.0)")
    conn.commit()
    return conn, path


def stub_sends(plain=None, buttons=None):
    """Point every outbound path at a recorder. Returns the call log.

    Each entry is (which_path, message, edit_id) so a test can assert not just that
    something was delivered but *how* — plain text or a keyboard, fresh or an edit.
    """
    log = []

    def _plain(msg, edit_id=None):
        log.append(("plain", msg, edit_id))
        return plain(msg, edit_id) if callable(plain) else plain

    def _buttons(msg, tid, edit_id=None):
        log.append(("buttons", msg, edit_id))
        return buttons(msg, edit_id) if callable(buttons) else buttons

    C._hermes_send_capture = _plain
    C.send_telegram_buttons_capture = _buttons
    C.send_telegram_buttons = lambda msg, tid: (_ for _ in ()).throw(
        AssertionError("the bool send is the last resort — not this path"))
    return log


def task(conn):
    return conn.execute("SELECT * FROM tasks WHERE id='T1'").fetchone()


def outbox_rows(conn):
    return conn.execute("SELECT event_type,payload_message,dispatch_status FROM transactional_outbox").fetchall()


def test_send_success_marks_dispatched():
    conn, path = fresh()
    log = stub_sends(plain="msg-111")
    notifier = lambda m: (_ for _ in ()).throw(AssertionError("fallback used though send succeeded"))
    C.escalate(conn, task(conn), "needs human", notifier, decision=False)
    rows = outbox_rows(conn)
    assert [e[0] for e in log] == ["plain"], f"wrong path: {log}"
    assert len(rows) == 1 and rows[0]["dispatch_status"] == 1, f"not marked dispatched: {list(rows[0])}"
    assert task(conn)["escalation_msg_id"] == "msg-111", "message_id not persisted for future edits"
    conn.close(); os.unlink(path)
    print("PASS  send-success: outbox row written AND marked dispatched; live send still fired")


def test_send_failure_persists_then_redelivers():
    conn, path = fresh()
    stub_sends(plain=None)                                   # every capture path DOWN
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


def test_decision_keeps_its_buttons():
    """A DECISION exists to be tapped. Edit-in-place dedup was added by routing every
    escalation through the plain-text capture, which carries no reply_markup — so decisions
    arrived with no Approve/Cancel at all. Dedup and buttons are not a trade-off."""
    conn, path = fresh()
    log = stub_sends(plain="plain-1", buttons="btn-1")
    notifier = lambda m: (_ for _ in ()).throw(AssertionError("fallback used though buttons succeeded"))
    C.escalate(conn, task(conn), "approve rail?", notifier, decision=True)
    assert [e[0] for e in log] == ["buttons"], f"decision did not use the keyboard path: {log}"
    assert outbox_rows(conn)[0]["dispatch_status"] == 1, "decision not marked dispatched"
    assert task(conn)["escalation_msg_id"] == "btn-1", "keyboard send must capture its id too"
    conn.close(); os.unlink(path)
    print("PASS  decision: keyboard path delivers, marks the outbox, and captures the msg_id")


def test_reescalation_edits_instead_of_spamming():
    conn, path = fresh()
    log = stub_sends(plain=lambda msg, edit_id: edit_id or "msg-111")
    notifier = lambda m: True
    C.escalate(conn, task(conn), "needs human", notifier, decision=False)
    C.escalate(conn, task(conn), "still needs human", notifier, decision=False)

    assert [e[2] for e in log] == [None, "msg-111"], f"second escalation was not an edit: {log}"
    assert task(conn)["escalation_count"] == 2, "occurrence count not persisted"
    assert "2×" in log[1][1], f"edited message does not show the repeat count: {log[1][1]!r}"
    conn.close(); os.unlink(path)
    print("PASS  dedup: a re-escalation edits the original message and counts the occurrence")


def test_legacy_db_without_dedup_columns_still_delivers():
    """The columns arrive via an additive ALTER in init_db. A DB that has not been through
    it must still deliver — dropping an 'a human is needed' message to save a dedup is the
    wrong trade."""
    conn, path = fresh(LEGACY_DDL)
    log = stub_sends(plain="msg-222")
    C.escalate(conn, task(conn), "needs human", lambda m: True, decision=False)
    assert [e[0] for e in log] == ["plain"], f"legacy DB did not deliver: {log}"
    assert outbox_rows(conn)[0]["dispatch_status"] == 1, "legacy DB escalation not dispatched"
    conn.close(); os.unlink(path)
    print("PASS  legacy DB: no dedup columns, still delivers and marks dispatched")


if __name__ == "__main__":
    _real_plain = C._hermes_send_capture
    _real_buttons = C.send_telegram_buttons_capture
    try:
        test_send_success_marks_dispatched()
        test_send_failure_persists_then_redelivers()
        test_decision_keeps_its_buttons()
        test_reescalation_edits_instead_of_spamming()
        test_legacy_db_without_dedup_columns_still_delivers()
    except AssertionError as e:
        print("FAIL ", e); sys.exit(1)
    finally:
        C._hermes_send_capture = _real_plain
        C.send_telegram_buttons_capture = _real_buttons
    print("ALL GREEN")
