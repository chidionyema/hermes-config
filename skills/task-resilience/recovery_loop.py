#!/usr/bin/env python3
"""
Recovery Loop — Automatic recovery routing for failed tasks.

Fires when a TaskResult has status != "success". Routes to the appropriate
recovery action based on error_class:

  error_class  | Action
  -------------|-------
  "transient"  | Retry with exponential backoff (3 attempts: 2s, 5s, 15s)
  "logic"      | Escalate to Claude strategist for replan; re-dispatch
  "blocked"    | Surface to user with specific blocker description

Usage:
    result = recovery_loop.execute_with_recovery(
        dispatch_fn=my_task_function,
        goal="Run integration tests",
        max_retries=3,
    )
    if result.needs_recovery:
        print(f"All recovery exhausted: {result.error}")
"""

import json
import time
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Callable, Optional, Any

from task_result import TaskResult, classify_text


# ── Backoff timing ───────────────────────────────────────────────────────────

# Exponential backoff delays in seconds (attempt 1, 2, 3, ...)
BACKOFF_DELAYS = [2, 5, 15]


def retry_backoff(attempt: int) -> float:
    """
    Get the backoff delay for a given attempt number (1-indexed).

    Returns the delay in seconds. Caps at the last defined delay.
    """
    idx = min(attempt - 1, len(BACKOFF_DELAYS) - 1)
    return BACKOFF_DELAYS[idx]


# ── Recovery log ─────────────────────────────────────────────────────────────

RECOVERY_LOG_DIR = Path.home() / ".hermes" / "task-state"
RECOVERY_LOG_FILE = RECOVERY_LOG_DIR / "recovery_log.jsonl"


def _ensure_log_dir():
    RECOVERY_LOG_DIR.mkdir(parents=True, exist_ok=True)


def log_recovery_event(event: dict):
    """Append a recovery event to the JSONL log."""
    _ensure_log_dir()
    event["timestamp"] = datetime.now(timezone.utc).isoformat()
    with open(RECOVERY_LOG_FILE, "a") as f:
        f.write(json.dumps(event) + "\n")


# ── Recovery actions ─────────────────────────────────────────────────────────

def retry_transient(
    dispatch_fn: Callable,
    goal: str,
    attempt: int,
    last_result: TaskResult,
    total_retries: int = 3,
) -> TaskResult:
    """
    Retry a transient failure with exponential backoff.

    Args:
        dispatch_fn: Zero-arg callable that dispatches the task and returns a TaskResult
        goal: Human-readable description of the task
        attempt: Current attempt number (1-indexed, 1 = first retry)
        last_result: The previous failed TaskResult
        total_retries: Maximum number of retry attempts

    Returns:
        TaskResult from the final attempt (success or last failure)
    """
    if attempt > total_retries:
        log_recovery_event({
            "event": "retry_exhausted",
            "goal": goal,
            "attempts": attempt - 1,
            "last_error": last_result.error,
            "last_error_class": last_result.error_class,
        })
        return TaskResult(
            status="failure",
            output=last_result.output,
            error=f"All {total_retries} retries exhausted. Last error: {last_result.error}",
            error_class="transient",
            exit_code=last_result.exit_code,
            context={"recovery": "retry_exhausted", "attempts": attempt - 1},
        )

    delay = retry_backoff(attempt)
    log_recovery_event({
        "event": "retry",
        "goal": goal,
        "attempt": attempt,
        "delay_seconds": delay,
        "last_error": last_result.error[:500],
    })

    time.sleep(delay)

    try:
        new_result = dispatch_fn()
    except Exception as e:
        new_result = TaskResult(
            status="failure",
            error=str(e),
            error_class="transient",
            context={"exception": str(e)},
        )

    if new_result.is_success:
        log_recovery_event({
            "event": "retry_success",
            "goal": goal,
            "attempt": attempt,
        })
        return new_result

    # Recurse for next attempt
    return retry_transient(dispatch_fn, goal, attempt + 1, new_result, total_retries)


def replan_logic(
    dispatch_fn: Callable,
    goal: str,
    strategist_fn: Optional[Callable],
    last_result: TaskResult,
) -> TaskResult:
    """
    Escalate a logic failure to the strategist for replanning, then re-dispatch.

    If no strategist_fn is provided, falls back to generating a structured
    replan prompt that the calling agent can use.

    Args:
        dispatch_fn: Zero-arg callable that dispatches the retry
        strategist_fn: Callable(goal, error_context) that returns a replan string
        last_result: The failed TaskResult (contains original goal + error context)
        goal: Original task goal description

    Returns:
        TaskResult from the re-dispatch, or failure summary if replan fails
    """
    error_context = {
        "original_goal": goal,
        "error": last_result.error[:2000],
        "output": last_result.output[:2000],
        "error_class": last_result.error_class,
        "exit_code": last_result.exit_code,
    }

    log_recovery_event({
        "event": "replan_started",
        "goal": goal,
        "error_context": error_context,
    })

    # Build structured replan prompt
    replan_prompt = json.dumps({
        "task": "replan_failed_task",
        "original_goal": goal,
        "what_went_wrong": last_result.error[:1000],
        "output_so_far": last_result.output[:1000],
        "instructions": (
            "Analyze the error above and produce a revised plan. "
            "The previous approach failed with a logic error. "
            "Output ONLY a JSON object with: "
            "{\"root_cause\": \"...\", \"revised_approach\": \"...\", "
            "\"revised_goal\": \"...\"}"
        ),
    })

    # Try strategist_fn if provided
    if strategist_fn is not None:
        try:
            strategist_response = strategist_fn(replan_prompt)
            try:
                replan = json.loads(strategist_response)
                revised_goal = replan.get("revised_goal", goal)
            except (json.JSONDecodeError, TypeError):
                revised_goal = strategist_response
        except Exception as e:
            log_recovery_event({
                "event": "replan_failed",
                "goal": goal,
                "error": str(e),
            })
            # Fall through to surface as blocked
            return TaskResult(
                status="failure",
                output=last_result.output,
                error=f"Replan failed — strategist error: {e}. Original: {last_result.error}",
                error_class="blocked",
                context={"recovery": "replan_strategist_error"},
            )
    else:
        # No strategist function provided; return the replan prompt
        # for the calling agent to act on
        log_recovery_event({
            "event": "replan_no_strategist",
            "goal": goal,
        })
        return TaskResult(
            status="partial",
            output=last_result.output,
            error=(
                f"[REPLAN NEEDED] Task failed with a logic error.\n"
                f"Goal: {goal}\n"
                f"Error: {last_result.error[:500]}\n"
                f"Structured replan prompt:\n{replan_prompt}"
            ),
            error_class="logic",
            context={"recovery": "replan_needs_calling_agent"},
        )

    # Re-dispatch with revised goal
    log_recovery_event({
        "event": "replan_redispatch",
        "goal": goal,
        "revised_goal": revised_goal,
    })

    try:
        new_result = dispatch_fn(revised_goal)
    except Exception as e:
        new_result = TaskResult(
            status="failure",
            error=f"Re-dispatch after replan failed: {e}",
            error_class="logic",
            context={"exception": str(e)},
        )

    if new_result.is_success:
        log_recovery_event({
            "event": "replan_success",
            "goal": goal,
            "revised_goal": revised_goal,
        })

    return new_result


def surface_blocked(
    goal: str,
    last_result: TaskResult,
) -> TaskResult:
    """
    Surface a blocked task to the user with specific blocker info.

    No automatic recovery — the task needs external input.

    Args:
        goal: Original task goal
        last_result: The blocked TaskResult

    Returns:
        TaskResult with status="failure", error_class="blocked", and a
        user-facing blocker description.
    """
    blocker_description = _format_blocker(goal, last_result)

    log_recovery_event({
        "event": "blocked_surfaced",
        "goal": goal,
        "error_class": last_result.error_class,
        "blocker": blocker_description,
    })

    return TaskResult(
        status="failure",
        output=last_result.output,
        error=blocker_description,
        error_class="blocked",
        exit_code=last_result.exit_code,
        context={"recovery": "blocked_surfaced", "blocker": blocker_description},
    )


def _format_blocker(goal: str, result: TaskResult) -> str:
    """Format a human-readable blocker message."""
    return (
        f"[BLOCKER] Task cannot proceed without external input.\n"
        f"  Goal: {goal}\n"
        f"  Specific issue: {result.error[:500]}\n"
        f"\n"
        f"  Action needed: {_suggest_blocker_action(result.error)}"
    )


def _suggest_blocker_action(error_text: str) -> str:
    """Suggest a user action based on blocker patterns."""
    err_lower = error_text.lower()

    if any(k in err_lower for k in ("api key", "auth", "token", "credential")):
        return "Provide the required API key, token, or credentials."
    if any(k in err_lower for k in ("permission", "access denied", "forbidden")):
        return "Grant file/system permissions or check access controls."
    if any(k in err_lower for k in ("not found", "no such file", "does not exist")):
        return "Verify the file path exists or provide the correct path."
    if any(k in err_lower for k in ("decision", "approval", "which", "choose")):
        return "Make a decision or provide guidance on how to proceed."
    if any(k in err_lower for k in ("not installed", "missing", "dependency")):
        return "Install the required dependency or provide install instructions."

    return "Review the blocker and provide the missing input or decision."


# ── Main recovery dispatcher ────────────────────────────────────────────────

def execute_with_recovery(
    dispatch_fn: Callable[[], TaskResult],
    goal: str,
    max_retries: int = 3,
    strategist_fn: Optional[Callable] = None,
) -> TaskResult:
    """
    Execute a task function with automatic recovery routing.

    This is the main entry point. Call it with a dispatch function that
    returns TaskResult. If the result is not success, the recovery loop fires.

    Args:
        dispatch_fn: Zero-arg callable that returns a TaskResult
        goal: Human-readable description of the task
        max_retries: Maximum retry attempts for transient failures (default: 3)
        strategist_fn: Optional callable(goal, error_context) for logic replan

    Returns:
        The final TaskResult after all recovery attempts.
    """
    _ensure_log_dir()

    log_recovery_event({
        "event": "dispatch_started",
        "goal": goal,
    })

    # Initial dispatch
    try:
        result = dispatch_fn()
    except Exception as e:
        result = TaskResult(
            status="failure",
            error=str(e),
            error_class="transient",
            context={"exception": str(e), "goal": goal},
        )

    log_recovery_event({
        "event": "initial_result",
        "goal": goal,
        "status": result.status,
        "error_class": result.error_class,
    })

    # If success, return immediately
    if result.is_success:
        log_recovery_event({
            "event": "dispatch_complete",
            "goal": goal,
            "status": "success",
        })
        return result

    # Recovery loop
    error_class = result.error_class or "transient"  # Default to transient if unknown

    if error_class == "transient":
        return retry_transient(
            dispatch_fn=dispatch_fn,
            goal=goal,
            attempt=1,
            last_result=result,
            total_retries=max_retries,
        )

    elif error_class == "logic":
        return replan_logic(
            dispatch_fn=dispatch_fn,
            goal=goal,
            strategist_fn=strategist_fn,
            last_result=result,
        )

    elif error_class == "blocked":
        return surface_blocked(goal=goal, last_result=result)

    else:
        # Unknown error class — treat as transient
        return retry_transient(
            dispatch_fn=dispatch_fn,
            goal=goal,
            attempt=1,
            last_result=result,
            total_retries=max_retries,
        )


# ── Resume-prompt extension ──────────────────────────────────────────────────

def get_recovery_resume_prompt() -> str:
    """
    Get a resume prompt that includes recovery info for interrupted tasks.

    Integrates with existing task_state.py's get_resume_prompt by adding
    recovery-awareness. Reads both current_task.json and recovery_log.jsonl.

    Returns:
        A prompt string for the agent, or empty string if nothing to resume.
    """
    from task_state import get_interrupted_task

    task = get_interrupted_task()
    if not task:
        return ""

    # Check recovery log for pending recovery actions
    pending_recoveries = []
    if RECOVERY_LOG_FILE.exists():
        try:
            with open(RECOVERY_LOG_FILE) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if entry.get("event") in ("blocked_surfaced", "replan_needs_calling_agent"):
                            pending_recoveries.append(entry)
                    except json.JSONDecodeError:
                        pass
        except OSError:
            pass

    prompt = f"""[TASK RESILIENCE — RECOVERY MODE]
You were interrupted while working on this task:

Task: {task['task']}
Started: {task['started_at']}
Last action: {task['last_action']}
Tools completed: {task['tool_calls_completed']}
"""

    if pending_recoveries:
        prompt += "\n⚠️ Pending recoveries detected:\n"
        for pr in pending_recoveries[-3:]:  # Show last 3
            prompt += f"  - [{pr['event']}] {pr.get('goal', '')}\n"
        prompt += (
            "\nRecovery instructions: Check each pending recovery above.\n"
            "  - BLOCKED: surface to user\n"
            "  - REPLAN NEEDED: use the structured prompt\n"
        )

    prompt += (
        "\nAuto-resume: Continue from where you left off. Do NOT ask the user what to do.\n"
        "They expect you to pick up exactly where you stopped. Check recovery status first.\n"
    )

    summary = task.get("conversation_summary", "")
    if summary:
        prompt += f"\n{summary}\n"

    return prompt


# ── CLI entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: recovery_loop.py [retry|replan|surface|resume-prompt|history]")
        print("\nCommands:")
        print("  retry <goal>               — simulate a transient retry (test)")
        print("  replan <goal> <error>      — simulate a logic replan (test)")
        print("  surface <goal> <error>     — simulate a blocked surface (test)")
        print("  resume-prompt              — get recovery-aware resume prompt")
        print("  history                    — show recovery log")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "retry":
        goal = " ".join(sys.argv[2:]) or "Test task"
        result = execute_with_recovery(
            dispatch_fn=lambda: TaskResult(status="failure", error="timeout", error_class="transient"),
            goal=goal,
            max_retries=1,  # Short for testing
        )
        print(result.to_json())

    elif cmd == "replan":
        goal = " ".join(sys.argv[2:3]) if len(sys.argv) > 2 else "Test task"
        error = " ".join(sys.argv[3:]) or "Logic error in output"
        result = replan_logic(
            dispatch_fn=lambda g: TaskResult(status="failure", error="re-dispatch failed"),
            goal=goal,
            strategist_fn=None,
            last_result=TaskResult(status="failure", error=error, error_class="logic"),
        )
        print(result.to_json())

    elif cmd == "surface":
        goal = " ".join(sys.argv[2:3]) if len(sys.argv) > 2 else "Test task"
        error = " ".join(sys.argv[3:]) or "Missing API key"
        result = surface_blocked(
            goal=goal,
            last_result=TaskResult(status="failure", error=error, error_class="blocked"),
        )
        print(result.to_json())

    elif cmd == "resume-prompt":
        prompt = get_recovery_resume_prompt()
        if prompt:
            print(prompt)
        else:
            print("No interrupted tasks to resume")

    elif cmd == "history":
        if RECOVERY_LOG_FILE.exists():
            with open(RECOVERY_LOG_FILE) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entry = json.loads(line)
                        print(json.dumps(entry, indent=2))
                        print("---")
        else:
            print("No recovery history found")
