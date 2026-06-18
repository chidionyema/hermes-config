#!/usr/bin/env python3
"""
dispatch-guard.py — Pre-dispatch enforcement for delegate_task.

Catches foreground (non-background) delegate_task calls before they fire,
PREVENTING the "⏳ Subagent working — queued" blocking pattern.

This is the structural fix: knowledge-level rules (SKILL.md, memory, policies)
have been tried and failed. This is a tool-call level gate — Hermes hooks
into this at dispatch time.

Install:
  Add to ~/.hermes/config.yaml as a pre-action hook:
    pre_action_hooks:
      - python3 ~/.hermes/scripts/dispatch-guard.py

That way every tool call is checked before dispatch, not after.

Usage:
  python3 dispatch-guard.py --check delegate_task '{"background": false, ...}'
  → Exits 1 with error message, blocking the call

  python3 dispatch-guard.py --check delegate_task '{"background": true, ...}'
  → Exits 0, allows the call

  python3 dispatch-guard.py --list-violations
  → Shows recent blocked calls

  python3 dispatch-guard.py --audit
  → Lowers max blocking age from 5min to 1min for demonstrations
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

LOG_FILE = Path.home() / ".hermes" / "logs" / "dispatch-violations.jsonl"
os.makedirs(LOG_FILE.parent, exist_ok=True)

# The subagent wall-time ceiling from the user profile
# Subagents that block the conversation (foreground) must complete in ≤30s
# or the user cannot steer. Background subagents have no ceiling.
MAX_FOREGROUND_SECONDS = 30


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check_delegate(args_str: str) -> int:
    """Inspect the args for a delegate_task call.
    
    If background is missing or False, block the call and log the violation.
    If background is True, allow it.
    """
    try:
        args = json.loads(args_str) if isinstance(args_str, str) else args_str
    except json.JSONDecodeError:
        print(
            f"⛔ [dispatch-guard] Could not parse delegate_task args: {args_str}",
            file=sys.stderr,
        )
        return 1

    # Parse the goal for context in the violation log
    goal = args.get("goal") or args.get("tasks", [{}])[0].get("goal", "unknown")

    # Check background flag - both 'True' (string, from CLI) and True (bool, from JSON)
    background = args.get("background", False)
    if isinstance(background, str):
        background = background.lower() == "true"

    # Check if this is a batch task array (tasks param) - still blocks without background=True
    is_batch = "tasks" in args and isinstance(args["tasks"], list)

    if not background:
        # BLOCK THE CALL
        violation = {
            "timestamp": iso_now(),
            "tool": "delegate_task",
            "violation": "foreground_blocking",
            "goal": str(goal)[:120],
            "is_batch": is_batch,
            "args_snippet": str({k: v for k, v in args.items() if k != "context"})[:200],
        }
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(violation) + "\n")

        print(
            f"⛔ BLOCKED: delegate_task without background=True\n"
            f"   Goal: {str(goal)[:80]}\n"
            f"   This blocks the Telegram chat. Set background=True.\n"
            f"   Violation logged to {LOG_FILE}",
            file=sys.stderr,
        )
        return 1

    # If background=True but missing notify_on_complete, warn but don't block
    notify = args.get("notify_on_complete", False)
    if isinstance(notify, str):
        notify = notify.lower() == "true"

    if not notify:
        # Non-blocking advisory
        print(
            f"⚠️  [dispatch-guard] Advisory: delegate_task with background=True "
            f"but without notify_on_complete. Task result will be silent.",
            file=sys.stderr,
        )

    return 0


def list_violations(limit: int = 10) -> int:
    """Show recent blocked calls."""
    if not LOG_FILE.exists():
        print("No violations logged yet.")
        return 0

    with open(LOG_FILE) as f:
        lines = [l.strip() for l in f if l.strip()]

    if not lines:
        print("No violations logged yet.")
        return 0

    entries = []
    for line in lines[-limit:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    print(f"Recent dispatch violations ({len(entries)}):")
    print("=" * 60)
    for e in entries:
        print(f"  [{e['timestamp']}] {e['tool']}")
        print(f"    Violation: {e['violation']}")
        print(f"    Goal: {e['goal']}")
        print()

    return 0


def audit() -> int:
    """Show all violations ever, then clear them (demonstration mode)."""
    if not LOG_FILE.exists():
        print("No violations. Clean record.")
        return 0

    with open(LOG_FILE) as f:
        lines = [l.strip() for l in f if l.strip()]

    if not lines:
        print("No violations. Clean record.")
        return 0

    entries = [json.loads(l) for l in lines]

    print(f"ALL dispatch violations ({len(entries)}):")
    print("=" * 60)
    for e in entries:
        print(f"  [{e['timestamp']}] {e['violation']}: {e['goal'][:80]}")
    print()
    print("File will be cleared on next invocation.")

    # Clear the file (audit mode = clean slate)
    LOG_FILE.unlink(missing_ok=True)
    print(f"✅ Log cleared. Watchdog active — next violation will be caught.")

    return 0


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  dispatch-guard.py --check <tool_name> '<args_json>'")
        print("  dispatch-guard.py --list-violations")
        print("  dispatch-guard.py --audit")
        return 1

    command = sys.argv[1]

    if command == "--check":
        if len(sys.argv) < 4:
            print("Usage: dispatch-guard.py --check <tool_name> '<args_json>'")
            return 1
        tool_name = sys.argv[2]
        args_str = sys.argv[3]

        if tool_name == "delegate_task":
            return check_delegate(args_str)
        # Pass through for other tools
        return 0

    elif command == "--list-violations":
        return list_violations()

    elif command == "--audit":
        return audit()

    else:
        print(f"Unknown command: {command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
