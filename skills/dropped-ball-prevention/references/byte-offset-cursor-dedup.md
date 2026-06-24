# Byte-Offset Cursor Dedup for Append-Only JSONL Logs

## Problem

A hook script runs on every event (e.g., post-correction), unconditionally appending a block
to a daily log. When events fire more often than actual data changes, the script produces
duplicate entries. In Otto's case, `reflect-on-correction.py` ran on every correction hook
but appended an "Auto-Reflection" block even when no new policy firings existed since the
last run, producing 66% noise (240 of 366 lines were duplicates).

## Solution: Byte-Offset Cursor

Track a byte offset into the append-only JSONL source file. On each run, only process
new lines past the cursor. Exit silently when the file hasn't grown.

### State file

```json
// ~/.hermes/state/<script-name>-last-run.json
{
  "last_run": "2026-06-23T10:21:21",
  "last_firing_cursor": 6792
}
```

### Core function

```python
def get_new_firings(cursor):
    """Get policy firings since the given byte offset cursor.
    Returns (list_of_new_firings, new_cursor)."""
    if not os.path.exists(FIRINGS_LOG):
        return [], cursor
    with open(FIRINGS_LOG) as f:
        # Handle truncation: reset cursor if file shrank
        f.seek(0, 2)
        file_size = f.tell()
        if cursor > file_size:
            cursor = 0
        f.seek(cursor)
        new_lines = f.readlines()
        new_cursor = f.tell()
    return [json.loads(l) for l in new_lines], new_cursor
```

### Main guard

```python
def main():
    state = load_state()
    new_firings, new_cursor = get_new_firings(state.get("last_firing_cursor", 0))

    # No new data since last run → exit silently
    if not new_firings:
        return 0

    # ... process new_firings, write ONE block ...

    # Persist cursor AFTER successful write
    save_state({"last_run": datetime.now().isoformat(),
                "last_firing_cursor": new_cursor})
```

## Why Byte Offset (Not Timestamp or Line Count)

- **Timestamp**: JSONL lines may arrive out of order; wall-clock comparisons are fragile.
- **Line count**: If the file is ever truncated and rewritten, the count resets but
  byte-offset handles truncation gracefully (resets to 0 when cursor > file_size).
- **Byte offset**: Deterministic, O(1) check, survives file truncation, works with any
  line format.

## Edge Cases Handled

| Scenario | Behavior |
|---|---|
| First run (no state) | cursor=0, all existing lines are "new" |
| No new data | exits 0, no file writes |
| File truncated | cursor reset to 0, re-processes all |
| File deleted | get_new_firings returns [], cursor unchanged |
| Concurrent appends | harmless — next run catches remaining lines |

## Verification Checklist

- [ ] Run script twice in a row with no new data → second run exits 0, no output
- [ ] Append a new JSONL line → next run detects it, appends ONE block
- [ ] Run again without new data → exits silently
- [ ] `grep -c "Auto-Reflection" <log>` never exceeds the number of actual data changes

## Worked Example

`~/.hermes/scripts/reflect-on-correction.py` — commit `704c7b3` on the `main` branch.
The script previously appended an Auto-Reflection block unconditionally on every
post-correction hook. After the fix, it exits silently when `policy-firings.jsonl` has
no new entries since the last cursor.
