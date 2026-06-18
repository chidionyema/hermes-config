#!/usr/bin/env python3
"""
outcome-evaluator.py — Self-detected failure evaluator for Otto.

Evaluates a task result against its success criteria and determines
pass/fail. On FAIL, triggers the reflect→policy loop. On PASS+exceptional,
captures a positive policy.

Usage:
    # After a task, evaluate its outcome:
    python3 outcome-evaluator.py --task-id <id> --exit-code <code> \
        --success-criteria "Criteria text" [--output-file <path>] \
        [--exceptional]

    # The script will:
    # 1. Determine pass/fail
    # 2. On FAIL: call reflect-on-correction.py + otto-learn add
    # 3. On PASS+exceptional: capture positive policy
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
POLICIES_DIR = HERMES_HOME / "policies"
FIRINGS_LOG = HERMES_HOME / "logs" / "policy-firings.jsonl"
INJECTION_LOG = HERMES_HOME / "logs" / "injection-log.jsonl"

ISO_NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
TODAY = datetime.now(timezone.utc).strftime("%Y%m%d")


def next_policy_id() -> str:
    """Generate the next policy id."""
    existing = list(POLICIES_DIR.glob(f"pol-{TODAY}-*.json"))
    seq = len(existing) + 1
    return f"pol-{TODAY}-{seq:03d}"


def log_injection(task_id: str, eval_result: dict):
    """Log the evaluation to injection-style log for traceability."""
    entry = {
        "timestamp": ISO_NOW,
        "event": "outcome_evaluation",
        "task_id": task_id,
        "result": eval_result["status"],
        "success_criteria": eval_result.get("success_criteria", ""),
        "exit_code": eval_result.get("exit_code"),
        "exceptional": eval_result.get("exceptional", False),
    }
    os.makedirs(INJECTION_LOG.parent, exist_ok=True)
    with open(INJECTION_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


def determine_outcome(exit_code: int, success_criteria: str, output_file: str | None, exceptional: bool) -> dict:
    """
    Determine pass/fail based on:
    1. Exit code 0 → PASS (structural success)
    2. Output file exists → PASS (if file was expected)
    3. Otherwise → FAIL
    
    Returns dict with status + rationale.
    """
    result = {
        "exit_code": exit_code,
        "success_criteria": success_criteria,
        "exceptional": exceptional,
        "status": "FAIL",
        "rationale": "",
    }

    reasons = []

    # Criterion 1: Exit code 0
    if exit_code == 0:
        reasons.append("Exit code 0 (structural success)")
        result["status"] = "PASS"

    # Criterion 2: Output file exists (if specified)
    if output_file and os.path.exists(os.path.expanduser(output_file)):
        reasons.append(f"Output file exists: {output_file}")
        result["status"] = "PASS"

    # Criterion 3: Error conditions
    if exit_code != 0:
        reasons.append(f"Exit code {exit_code} (non-zero)")
    
    # Special: Kill signal often means timeout
    if exit_code < 0:
        reasons.append(f"Process killed by signal {-exit_code}")
        result["status"] = "FAIL"
        result["failure_type"] = "TRANSIENT" if exit_code in (-9, -15) else "LOGIC"

    result["rationale"] = "; ".join(reasons) if reasons else "No criteria matched"

    if result["status"] == "FAIL":
        # Determine failure type from criteria
        timeout_keywords = ["timeout", "time", "deadline", "slow"]
        logic_keywords = ["should", "expected", "wrong", "incorrect", "bug"]
        if any(kw in success_criteria.lower() for kw in timeout_keywords):
            result["failure_type"] = "TRANSIENT"
        elif any(kw in success_criteria.lower() for kw in logic_keywords):
            result["failure_type"] = "LOGIC"
        else:
            result["failure_type"] = "LOGIC"  # Default

    return result


def handle_fail(eval_result: dict, task_id: str):
    """
    On FAIL:
    1. Call reflect-on-correction.py
    2. Add a policy via otto-learn
    3. Log the failure
    """
    print(f"\n  ❌ FAIL detected for task '{task_id}'")
    print(f"     Rationale: {eval_result['rationale']}")
    print(f"     Failure type: {eval_result.get('failure_type', 'unknown')}")

    # Step 1: Run reflection
    print("  → Running post-failure reflection...")
    try:
        ref_script = HERMES_HOME / "scripts" / "reflect-on-correction.py"
        if ref_script.exists():
            result = subprocess.run(
                [sys.executable, str(ref_script)],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                print(f"    ✅ Reflection: {result.stdout.strip()[:100]}")
            else:
                print(f"    ⚠️ Reflection warning: {result.stderr.strip()[:100]}")
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"    ⚠️ Reflection error: {e}")

    # Step 2: Add a policy
    print("  → Adding failure policy...")
    trigger = eval_result["rationale"][:80]
    rule = (
        f"When outcome evaluator detects failure (exit code {eval_result['exit_code']}): "
        f"{eval_result['success_criteria'][:80]}. "
        f"Failure type: {eval_result.get('failure_type', 'unknown')}."
    )
    try:
        learn_script = HERMES_HOME / "scripts" / "otto-learn.py"
        if learn_script.exists():
            result = subprocess.run(
                [sys.executable, str(learn_script), "add", trigger, rule,
                 "--source", f"auto-detected failure: {task_id}"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                print(f"    ✅ Policy added: {result.stdout.strip()}")
            else:
                print(f"    ⚠️ Policy add warning: {result.stderr.strip()[:100]}")
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"    ⚠️ Policy add error: {e}")

    return False


def handle_pass(eval_result: dict, task_id: str):
    """
    On PASS:
    1. If exceptional, capture a positive policy
    2. Log the success
    """
    print(f"\n  ✅ PASS detected for task '{task_id}'")

    if eval_result.get("exceptional"):
        print("  → Task was exceptional — capturing positive policy...")
        trigger = f"Success pattern: {eval_result['success_criteria'][:80]}"
        rule = (
            f"Positive reinforcement: {eval_result['rationale']}. "
            f"This pattern worked well and should be repeated."
        )
        try:
            learn_script = HERMES_HOME / "scripts" / "otto-learn.py"
            if learn_script.exists():
                result = subprocess.run(
                    [sys.executable, str(learn_script), "add", trigger, rule,
                     "--source", f"auto-detected exceptional success: {task_id}"],
                    capture_output=True, text=True, timeout=30
                )
                if result.returncode == 0:
                    print(f"    ✅ Positive policy added: {result.stdout.strip()}")
                else:
                    print(f"    ⚠️ Policy add warning: {result.stderr.strip()[:100]}")
        except (subprocess.TimeoutExpired, OSError) as e:
            print(f"    ⚠️ Policy add error: {e}")
    else:
        print("  → Task passed normally (no exceptional flag).")

    return True


def main():
    parser = argparse.ArgumentParser(description="Outcome evaluator for Otto tasks")
    parser.add_argument("--task-id", required=True, help="Task identifier")
    parser.add_argument("--exit-code", type=int, required=True, help="Task exit code")
    parser.add_argument("--success-criteria", required=True, help="Expected success criteria")
    parser.add_argument("--output-file", help="Expected output file path")
    parser.add_argument("--exceptional", action="store_true", help="Mark as exceptional result")
    parser.add_argument("--verbose", action="store_true", help="Detailed output")

    args = parser.parse_args()

    print(f"🔍 Outcome Evaluation — {args.task_id}")
    print(f"   Exit code: {args.exit_code}")
    print(f"   Success criteria: {args.success_criteria[:80]}...")

    eval_result = determine_outcome(
        exit_code=args.exit_code,
        success_criteria=args.success_criteria,
        output_file=args.output_file,
        exceptional=args.exceptional,
    )

    log_injection(args.task_id, eval_result)

    if eval_result["status"] == "FAIL":
        handle_fail(eval_result, args.task_id)
    else:
        handle_pass(eval_result, args.task_id)

    if args.verbose:
        print(f"\n--- Full Evaluation ---")
        print(json.dumps(eval_result, indent=2))

    print()
    return 0 if eval_result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
