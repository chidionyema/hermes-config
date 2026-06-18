#!/usr/bin/env python3
"""
Task Resilience — Integration module.

Auto-loads with the Hermes task-resilience skill. Provides:
1. Structured result wrapper for every delegated task
2. Recovery routing (retry/replan/surface) on non-success
3. Async job queue for background task dispatch
4. Recovery-aware resume-prompt extension

This module does NOT modify existing task_state.py. It adds new capabilities
alongside it.

Usage from Hermes skill:
    from task_result import TaskResult, wrap_delegate_result, classify_task_output
    from recovery_loop import execute_with_recovery, get_recovery_resume_prompt
    from async_queue import create_job, get_pending_jobs
"""

from task_result import (
    TaskResult,
    wrap_delegate_result,
    classify_task_output,
    classify_text,
)

from recovery_loop import (
    execute_with_recovery,
    retry_transient,
    replan_logic,
    surface_blocked,
    get_recovery_resume_prompt,
    RECOVERY_LOG_FILE,
)

from async_queue import (
    Job,
    create_job,
    get_job,
    get_pending_jobs,
    list_jobs,
    cleanup_old_jobs,
)


# ── Convenience: dispatch with recovery ──────────────────────────────────────

def safe_dispatch(
    dispatch_fn,
    goal: str,
    max_retries: int = 3,
    strategist_fn=None,
) -> TaskResult:
    """
    Convenience: execute dispatch_fn with full recovery routing.

    One-call entry point for any task dispatch:
        result = safe_dispatch(
            dispatch_fn=lambda: run_my_task(),
            goal="Run integration tests",
        )
        if not result.is_success:
            handle_failure(result)

    Args:
        dispatch_fn: Zero-arg callable that returns a TaskResult
        goal: Human-readable task description
        max_retries: Max retry attempts for transient failures
        strategist_fn: Optional callable for logic replan

    Returns:
        Final TaskResult after all recovery attempts.
    """
    return execute_with_recovery(
        dispatch_fn=dispatch_fn,
        goal=goal,
        max_retries=max_retries,
        strategist_fn=strategist_fn,
    )


# ── Integration hooks for existing task_state.py ─────────────────────────────

def enhanced_resume_prompt() -> str:
    """
    Get a resume prompt that includes recovery info.

    Wraps task_state.get_resume_prompt() and appends recovery-aware
    context for failed/blocked tasks.

    Returns:
        Prompt string for agent, or "" if nothing to resume.
    """
    import task_state

    base_prompt = task_state.get_resume_prompt()
    if not base_prompt:
        return ""

    recovery_prompt = get_recovery_resume_prompt()
    if recovery_prompt:
        return recovery_prompt

    return base_prompt


def check_recovery_on_resume() -> str:
    """
    Check for pending recoveries and return a formatted summary.

    Call this during session startup to detect tasks that need
    recovery action. Integrates with task_state's auto-resume.

    Returns:
        A formatted string for the agent, or empty string if nothing pending.
    """
    from task_state import get_interrupted_task

    task = get_interrupted_task()
    pending_jobs = get_pending_jobs()

    if not task and not pending_jobs:
        return ""

    lines = ["[TASK RESILIENCE — RECOVERY CHECK]"]

    if task:
        lines.append(f"  Interrupted task: {task['task']}")
        lines.append(f"  Last action: {task['last_action']}")

    if pending_jobs:
        lines.append(f"  Pending recoveries: {len(pending_jobs)} job(s)")
        for job in pending_jobs[:5]:
            lines.append(f"    - [{job.status}] {job.goal[:60]}")

    lines.append("")
    lines.append("  Check and execute recovery for each item above.")
    lines.append("  Use recovery_loop.execute_with_recovery() or Job.execute_recovery().")

    return "\n".join(lines)


# ── CLI entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: __init__.py [check|resume-prompt|safe-dispatch <goal>]")
        print("\nCommands:")
        print("  check               — check for pending recoveries")
        print("  resume-prompt       — get recovery-aware resume prompt")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "check":
        result = check_recovery_on_resume()
        if result:
            print(result)
        else:
            print("✅ No pending recoveries")

    elif cmd == "resume-prompt":
        prompt = enhanced_resume_prompt()
        if prompt:
            print(prompt)
        else:
            print("No interrupted tasks to resume")
