#!/usr/bin/env python3
"""
LUX Task Resilience — Auto-recovery for interrupted tasks.

Drop this file in ~/.hermes/skills/task-resilience/
Hermes will auto-load it as a skill.

What it does:
1. Before every tool call, saves the current task state
2. On session start, checks for interrupted tasks
3. Auto-resumes: "You were working on X. Continue from where you left off."
4. On completion, clears the saved state

The user NEVER has to re-prompt. The agent ALWAYS picks up where it left off.
"""

import json
import os
from pathlib import Path
from datetime import datetime, timezone

STATE_DIR = Path(os.environ.get("HERMES_TASK_STATE_DIR")
                 or Path.home() / ".hermes" / "task-state")
STATE_FILE = STATE_DIR / "current_task.json"


def save_task_state(
    task_description: str,
    conversation_summary: str = "",
    tool_calls_completed: int = 0,
    last_action: str = "",
    metadata: dict | None = None,
) -> None:
    """Save the current task state before each tool call."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    
    state = {
        "task": task_description,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "conversation_summary": conversation_summary,
        "tool_calls_completed": tool_calls_completed,
        "last_action": last_action,
        "interrupted": True,  # Always True until task completes
        "metadata": metadata or {},
    }
    
    STATE_FILE.write_text(json.dumps(state, indent=2))


def get_interrupted_task() -> dict | None:
    """Check if there's an interrupted task that needs resuming."""
    if not STATE_FILE.exists():
        return None
    
    try:
        state = json.loads(STATE_FILE.read_text())
        if state.get("interrupted"):
            return state
    except (json.JSONDecodeError, KeyError):
        pass
    
    return None


def mark_task_complete() -> None:
    "Mark the current task as complete and log an outcome record."
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text())
            should_log = bool(state.get("task", "")) and state.get("tool_calls_completed", 0) > 0
            task_desc = state.get("task", "completed")
            state["interrupted"] = False
            state["completed_at"] = datetime.now(timezone.utc).isoformat()
            state["last_updated"] = datetime.now(timezone.utc).isoformat()
            STATE_FILE.write_text(json.dumps(state, indent=2))
            if should_log:
                import subprocess
                hermes_home = os.path.expanduser("~/.hermes")
                outcome_script = os.path.join(hermes_home, "scripts", "outcome-accelerator.py")
                if os.path.exists(outcome_script):
                    try:
                        subprocess.run(
                            [sys.executable, outcome_script, task_desc[:200]],
                            timeout=5, capture_output=True, text=True,
                        )
                    except (subprocess.TimeoutExpired, OSError):
                        pass
                # Also log to audit trail
                audit_script = os.path.join(hermes_home, "scripts", "audit-trail.py")
                if os.path.exists(audit_script):
                    try:
                        subprocess.run(
                            [sys.executable, audit_script, "task_complete", task_desc[:150], "auto-logged"],
                            timeout=5, capture_output=True, text=True,
                        )
                    except (subprocess.TimeoutExpired, OSError):
                        pass
        except (json.JSONDecodeError, KeyError):
            pass


def get_resume_prompt() -> str:
    """Generate a resume prompt for the agent."""
    task = get_interrupted_task()
    if not task:
        return ""
    
    return f"""[TASK RESILIENCE]
You were interrupted while working on this task:

Task: {task['task']}
Started: {task['started_at']}
Last action: {task['last_action']}
Tools completed: {task['tool_calls_completed']}

Auto-resume: Continue from where you left off. Do NOT ask the user what to do.
They expect you to pick up exactly where you stopped. If you were reading a file,
re-read it to get current state. If you were about to make an edit, check if the
edit was already applied. Pick up and continue.

{task.get('conversation_summary', '')}
"""


if __name__ == "__main__":
    # CLI for manual task state management
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: task-state.py [save|check|clear|resume-prompt]")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "save":
        task = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "Unknown task"
        save_task_state(task, last_action="manual save")
        print(f"✅ Saved: {task}")
    
    elif cmd == "check":
        task = get_interrupted_task()
        if task:
            print(f"⚠️  Interrupted task: {task['task']}")
            print(f"   Started: {task['started_at']}")
            print(f"   Tools completed: {task['tool_calls_completed']}")
        else:
            print("✅ No interrupted tasks")
    
    elif cmd == "clear":
        mark_task_complete()
        print("✅ Task marked complete")
    
    elif cmd == "resume-prompt":
        prompt = get_resume_prompt()
        if prompt:
            print(prompt)
        else:
            print("No interrupted tasks to resume")
