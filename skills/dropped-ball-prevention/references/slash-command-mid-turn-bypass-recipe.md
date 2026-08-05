# Slash-Command Mid-Turn Bypass Recipe

## Symptom

A registered slash command (e.g. `/summary`, `/foo`) returns

```
⏳ Agent is running — `/foo` can't run mid-turn. Wait for the current
response or `/stop` first.
```

…while the agent is busy, even though the command has a valid handler
(`gateway/slash_commands.py:_*_command`) and works fine when the agent
is idle. The user expected the command to fire and report a result.

## Root Cause (Hermes `gateway/run.py`)

The running-agent guard at line 7318 has a bypass allowlist:
`_DEDICATED_HANDLERS` (imported from `hermes_cli.commands.ACTIVE_SESSION_BYPASS_COMMANDS`)
plus an explicit branch list immediately after (help, commands, profile,
update, version, panel, inbox, fleet, brief, missions, revert, cron,
busy, notify). Any command NOT in either set hits the catch-all at
~line 7358 which returns the "can't run mid-turn" rejection.

The defense exists for a reason: a slash command that hits the
running-agent interrupt path will be silently discarded by the safety
net (`#5057`, `#6252`, `#10370`). The catch-all is the explicit
"rejected gracefully" path so users see *something*.

## The 4-Step Fix

A fix that touches the bypass list must touch **both** the explicit
branch and the frozenset, then add tests that pin both. Skipping the
frozenset (or the branch) creates the conditions for a future "polish"
commit to silently revert half the fix.

### 1. Add explicit branch in `gateway/run.py` (line 7318 block)

```python
if _cmd_def_inner and _cmd_def_inner.name in _DEDICATED_HANDLERS:
    if _cmd_def_inner.name == "help":
        return await self._handle_help_command(event)
    if _cmd_def_inner.name == "summary":           # NEW
        return await self._handle_summary_command(event)   # NEW
    if _cmd_def_inner.name == "commands":
        ...
```

### 2. Add to the frozenset in `hermes_cli/commands.py` (~line 376)

```python
ACTIVE_SESSION_BYPASS_COMMANDS: frozenset[str] = frozenset(
    {
        "agents",
        ...
        "stop",
        "summary",   # NEW
        "update",
        ...
    }
)
```

### 3. Add behavioral regression test (handler is awaited)

In `tests/gateway/test_running_agent_session_toggles.py` (the file
that already covers `/yolo`, `/verbose`, `/btw` mid-turn):

```python
async def test_summary_dispatches_mid_run():
    runner = _make_runner()
    runner._handle_summary_command = AsyncMock(
        return_value="Current conversation summary"
    )
    result = await runner._handle_message(_make_event("/summary"))
    runner._handle_summary_command.assert_awaited_once()
    assert result == "Current conversation summary"
    assert "can't run mid-turn" not in result
```

This catches the case where someone removes the bypass entirely — the
handler is awaited 0× and the test fails.

### 4. Add module-load invariant test (defense against polish commits)

Same file, plain `def` (no async):

```python
def test_summary_in_active_session_bypass_commands():
    """'summary' must be in ACTIVE_SESSION_BYPASS_COMMANDS.

    Defends against 'polish' commits that strip the frozenset entry
    while claiming unrelated cleanup. Without this, a future commit
    could remove 'summary' from the frozenset — and only the explicit
    branch would still keep /summary working mid-turn — until the next
    refactor consolidates both paths and the bug returns silently.
    """
    from hermes_cli.commands import ACTIVE_SESSION_BYPASS_COMMANDS
    assert "summary" in ACTIVE_SESSION_BYPASS_COMMANDS, (
        "'summary' was removed from ACTIVE_SESSION_BYPASS_COMMANDS — "
        "/summary will hit the running-agent catch-all."
    )
```

This is the durable substrate: a plain import-time check that breaks
CI the moment someone deletes the line. Test count goes from 6 → 7.

## Why Both Step 3 and Step 4

Step 3 (behavioral) proves the end-to-end path works. Step 4
(invariant) proves a structural property of the source. If only step 3
exists, a future "consolidate the bypass into a single dispatch table"
refactor could silently drop the explicit branch — step 3 would still
pass because the frozenset membership catches it. If only step 4
exists, a future "remove dead code" sweep that removes the explicit
branch entirely would still pass because the frozenset still has the
entry. **Both are needed.** They cover orthogonal regressions.

## Why This Matters in Practice

The 2026-08-04 `/summary` bug "came back" because of exactly this
pattern:

```
72f6cedab6  fix(gateway): allow summary command mid-turn       # Claude added bypass + frozenset
7f541fe4a3  polish: replace em-dashes with -- in commercial_ui.py and health_panel.py
```

The polish commit only deleted the 4 lines Claude added (bypass +
frozenset) — it touched NO em-dashes in `gateway/run.py` or
`hermes_cli/commands.py`. The commit message lied about its diff. The
only way to find this is `git show 7f541fe4a3` and read the `-` lines.

**Defense:** any commit that touches `gateway/run.py` line 7318
or `hermes_cli/commands.py` line 376 must keep `summary` in both
places. The step-4 invariant test enforces that.

## What If the Handler Doesn't Exist?

If `_handle_<name>_command` is not defined, the bypass isn't the
problem — the command is genuinely not implemented. Add the handler
in `gateway/slash_commands.py` (the `GatewaySlashCommandsMixin`) before
adding it to the bypass.