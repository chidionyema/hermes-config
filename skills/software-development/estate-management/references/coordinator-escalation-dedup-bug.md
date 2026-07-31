# Coordinator Escalation Dedup — Stale Dict Bug

**Root cause discovered 2026-07-31:** The coordinator's `escalate()` function has edit-in-place
dedup logic that should prevent repeated "ESCALATED" messages by editing the existing
Telegram message. But it was broken because it read `escalation_msg_id` from a stale
`task` dict instead of from the database.

## The Bug

```python
# coordinator.py escalate() — BEFORE fix
existing_id = task.get("escalation_msg_id")  # ALWAYS None
count = (task.get("escalation_count") or 0) + 1  # ALWAYS 1
```

The `task` dict was loaded from the DB before the first escalation. When `_set()` wrote
`escalation_msg_id` and `escalation_count` to the DB, the in-memory `task` dict wasn't
updated. Next tick, `task.get("escalation_msg_id")` returned None → dedup never triggered
→ fresh message sent every coordinator tick.

## The Fix

```python
# coordinator.py escalate() — AFTER fix
row = conn.execute(
    "SELECT escalation_msg_id, escalation_count FROM tasks WHERE id=?",
    (task["id"],)).fetchone()
existing_id = (row["escalation_msg_id"] if row else None) or task.get("escalation_msg_id")
count = ((row["escalation_count"] if row else None) or task.get("escalation_count") or 0) + 1
```

Read fresh from the DB before checking. The fallback to `task.get()` handles the first-ever
escalation where neither source has a value.

## Diagnostic Query

To check if the bug is active (all escalated tasks should have escalating counts):

```sql
SELECT id, title, escalation_msg_id, escalation_count
FROM tasks
WHERE status = 'escalated';
```

If `escalation_msg_id` is NULL and `escalation_count` is 0 for tasks that have been
escalated multiple times, the bug is active. The fix is self-healing: next escalation
sends one final fresh message (since no existing ID to edit), captures it, and subsequent
escalations edit in-place.

## Related: progress_notify Already Works

The `progress_notify()` function (for "Working on" / "Verifying" messages) was already
correct — it reads `progress_msg_id` from the DB directly:

```python
row = conn.execute("SELECT progress_msg_id FROM tasks WHERE id=?", (tid,)).fetchone()
msg_id = row[0] if row else None
```

This is the same pattern the escalate() fix uses. The progress messages were never
broken — only the escalation messages were repeating.

## Pitfall: task dict staleness

Any function that both writes to the DB (via `_set()`) and later reads that same field
from a `task` dict loaded earlier will encounter this bug. The `task` dict is a snapshot
at load time. After `_set()` writes, only the DB has the new value. Pattern to use:

```python
# WRONG: read from task dict (stale after _set())
value = task.get("field_name")

# RIGHT: read from DB (always current)
row = conn.execute("SELECT field_name FROM tasks WHERE id=?", (task["id"],)).fetchone()
value = (row["field_name"] if row else None) or task.get("field_name")
```
