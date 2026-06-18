#!/usr/bin/env python3
"""
Task Result — Structured result wrapper for delegate_task calls.

Wraps any task dispatch, parses output, and returns a structured result
with explicit status + error classification. No task resolves without
a status field.

Status values:
  - "success":   task completed as expected
  - "failure":   task ran but produced error output
  - "partial":   task partially completed (some work done, some failed)

Error classes:
  - "transient": retriable (timeout, rate-limit, resource contention, network)
  - "logic":     approach was wrong (bad output, failed validation, wrong direction)
  - "blocked":   external dependency missing (auth, API key, user decision, missing dep)
  - None:        no error (success status)

Usage:
    result = wrap_delegate_task(goal="Run tests", output="...")
    # or parse raw terminal/subagent output
    result = classify_task_output(exit_code=1, stdout="...", stderr="...")
"""

import json
import re
from dataclasses import dataclass, field, asdict
from typing import Optional


# ── Structured result dataclass ──────────────────────────────────────────────

@dataclass
class TaskResult:
    """Structured result for every delegated task."""
    status: str                              # "success" | "failure" | "partial"
    output: str = ""
    error: str = ""
    error_class: Optional[str] = None        # "transient" | "logic" | "blocked" | None
    exit_code: Optional[int] = None
    context: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @property
    def is_success(self) -> bool:
        return self.status == "success"

    @property
    def needs_recovery(self) -> bool:
        return self.status in ("failure", "partial")


# ── Heuristic classifiers ────────────────────────────────────────────────────

# Patterns suggesting transient failures (retriable)
_TRANSIENT_PATTERNS = [
    r"(?i)(timeout|timed?\s*out)",
    r"(?i)(rate\s*limit|rate_limit|throttl)",
    r"(?i)(resource\s*contention|too\s*many\s*open\s*files)",
    r"(?i)(connection\s*refused|connection\s*reset|network\s*error)",
    r"(?i)(temporarily\s*unavailable|service\s*unavailable)",
    r"(?i)(5\d{2}\s*server\s*error|502|503|504)",
    r"(?i)(background\s*process\s*killed|OOM|out\s*of\s*memory)",
    r"(?i)(could\s*not\s*resolve|DNS\s*lookup\s*failed)",
    r"(?i)(exceeded.*timeout|maximum\s*execution\s*time)",
]

# Patterns suggesting logic failures (replan needed)
_LOGIC_PATTERNS = [
    r"(?i)(failed\s*validation|validation\s*failed)",
    r"(?i)(assertion\s*error|assert\s+false)",
    r"(?i)(compilation\s*error|syntax\s*error)",
    r"(?i)(test\s*failed|tests?\s+fail)",
    r"(?i)(unexpected\s*output|wrong\s*output|incorrect\s*result)",
    r"(?i)(does\s+not\s+match\s+expected|expected.*but\s*got)",
    r"(?i)(approach\s*is\s*wrong|rethink|replan)",
    r"(?i)(lint\s*error|type\s*error|import\s*error|module\s*not\s*found)",
    r"(?i)(build\s*failed|non-zero\s*exit\s*code\s+(1|2))",
]

# Patterns suggesting blocked failures (needs user/input)
_BLOCKED_PATTERNS = [
    r"(?i)(missing\s*(API|key|auth|token|credential|environment|env|dep|dependency))",
    r"(?i)(permission\s*denied|access\s*denied|forbidden|unauthorized)",
    r"(?i)(requires\s*user\s*(input|action|decision|approval))",
    r"(?i)(BLOCKED:)",
    r"(?i)(execute_code\s*script\s*blocked|timed\s*out\s*without\s*user)",
    r"(?i)(needs\s*a\s*decision|needs\s*approval|awaiting\s*input)",
    # "not found" for files/paths only — must not match ModuleNotFoundError
    r"(?i)(FileNotFoundError|No\s+such\s+file|does\s+not\s+exist)",
]


def classify_text(text: str) -> Optional[str]:
    """
    Classify a text string into an error class using heuristic patterns.

    Returns "transient", "logic", "blocked", or None if no match.
    Checks blocked first (highest priority, user-action-needed),
    then transient (retriable), then logic.
    """
    if not text:
        return None

    for pattern in _BLOCKED_PATTERNS:
        if re.search(pattern, text):
            return "blocked"

    for pattern in _TRANSIENT_PATTERNS:
        if re.search(pattern, text):
            return "transient"

    for pattern in _LOGIC_PATTERNS:
        if re.search(pattern, text):
            return "logic"

    return None


def classify_exit_code(code: Optional[int]) -> Optional[str]:
    """Classify a numeric exit code into an error class."""
    if code is None:
        return None
    if code in (0,):
        return None
    if code in (-9, -15, 137, 143):  # Killed by signal
        return "transient"
    if code in (-6,):  # Abort
        return "logic"
    # Non-zero generally suggests logic, but we default to None
    # so text classification takes priority
    return None


# ── Main classification function ─────────────────────────────────────────────

def classify_task_output(
    exit_code: Optional[int] = None,
    stdout: str = "",
    stderr: str = "",
    combined: Optional[str] = None,
) -> TaskResult:
    """
    Classify the output of a completed task into a structured TaskResult.

    Args:
        exit_code: Return code of the process (None if unknown)
        stdout: Standard output text
        stderr: Standard error text
        combined: Combined output (if stdout/stderr aren't separated)

    Returns:
        TaskResult with status, error, and error_class populated.
    """
    output_text = combined or (stdout + "\n" + stderr)
    error_text = stderr or combined or ""

    # Default: success on exit code 0 with no stderr
    if exit_code == 0 and not error_text.strip():
        return TaskResult(
            status="success",
            output=stdout or output_text,
            exit_code=0,
        )

    # Determine status
    if exit_code is not None and exit_code != 0:
        status = "failure"
    elif error_text.strip():
        status = "failure"
    else:
        status = "success"

    # Classify error
    error_class = classify_text(output_text)
    if error_class is None:
        error_class = classify_exit_code(exit_code)

    # If we have a non-zero exit code but no pattern match, default to logic
    if error_class is None and exit_code is not None and exit_code != 0:
        error_class = "logic"

    return TaskResult(
        status=status,
        output=output_text,
        error=error_text[:2000] if error_text else "",
        error_class=error_class,
        exit_code=exit_code,
    )


def wrap_delegate_result(
    raw_output: str,
    goal: str = "",
) -> TaskResult:
    """
    Wrap a delegate_task's raw output string into a structured TaskResult.

    Handles common Hermes delegate_task output formats:
    - JSON-structured responses ({"status": ..., "output": ...})
    - Free-text summaries
    - Error messages

    Args:
        raw_output: The raw output string from delegate_task
        goal: The original goal/prompt sent to the subagent (for context)

    Returns:
        TaskResult with best-effort classification.
    """
    # Try to parse JSON output first
    try:
        data = json.loads(raw_output)
        if isinstance(data, dict):
            status = data.get("status", "success")
            if status not in ("success", "failure", "partial"):
                status = "success" if not data.get("error") else "failure"

            return TaskResult(
                status=status,
                output=data.get("output", data.get("summary", raw_output)),
                error=data.get("error", data.get("stderr", "")),
                error_class=data.get("error_class"),
                exit_code=data.get("exit_code"),
                context={"goal": goal, "parsed_json": True},
            )
    except (json.JSONDecodeError, TypeError):
        pass

    # Fall back to heuristic classification
    # Use stdout-only path so successful text isn't mistaken for an error
    return classify_task_output(
        stdout=raw_output,
        stderr="",
        exit_code=0,  # Assume success for free-text output
    )


# ── CLI entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: task_result.py [classify|wrap] <text>")
        print("\n  classify <text>  — classify text as transient/logic/blocked/none")
        print("  wrap <text>     — wrap raw output as structured result")
        sys.exit(1)

    cmd = sys.argv[1]
    text = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""

    if cmd == "classify":
        cls = classify_text(text)
        print(json.dumps({"error_class": cls}, indent=2))

    elif cmd == "wrap":
        result = wrap_delegate_result(text)
        print(result.to_json())

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
