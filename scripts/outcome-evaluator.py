#!/usr/bin/env python3
"""
outcome-evaluator.py — F2-aware outcome evaluator.

Replaces binary PASS/FAIL with a calibrated confidence spectrum (0.0–1.0).
Low-confidence results are auto-flagged for review.
Divergence detection is passive — uses user corrections as the holdout.

Usage:
    python3 outcome-evaluator.py --task-id <id> --exit-code <code> \\
        --success-criteria "Criteria text" [--output-file <path>] \\
        [--duration <seconds>] [--exceptional]
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
CONFIDENCE_SCRIPT = HERMES_HOME / "scripts" / "eval-confidence.py"

ISO_NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
TODAY = datetime.now(timezone.utc).strftime("%Y%m%d")

# Thresholds
FLAG_THRESHOLD = 0.60  # below this → auto-flag
FAIL_THRESHOLD = 0.30   # below this → structural fail
HIGH_CONFIDENCE = 0.85  # above this → high confidence


def next_policy_id() -> str:
    existing = list(POLICIES_DIR.glob(f"pol-{TODAY}-*.json"))
    return f"pol-{TODAY}-{len(existing) + 1:03d}"


def log_injection(task_id: str, eval_result: dict):
    entry = {
        "timestamp": ISO_NOW,
        "event": "outcome_evaluation",
        "task_id": task_id,
        "result": eval_result["status"],
        "confidence_score": eval_result.get("confidence_score", 0.5),
        "confidence_bucket": eval_result.get("confidence_bucket", "unknown"),
        "success_criteria": eval_result.get("success_criteria", ""),
        "exit_code": eval_result.get("exit_code"),
        "exceptional": eval_result.get("exceptional", False),
        "flagged": eval_result.get("flagged", False),
    }
    os.makedirs(INJECTION_LOG.parent, exist_ok=True)
    with open(INJECTION_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


def get_confidence(exit_code: int, success_criteria: str,
                   output_file: str | None, task_duration_s: float | None) -> dict:
    """Get confidence score from the F2 confidence engine."""
    try:
        cmd = [
            sys.executable, str(CONFIDENCE_SCRIPT),
            "--score",
            "--exit-code", str(exit_code),
            "--success-criteria", success_criteria,
        ]
        if output_file:
            cmd += ["--output-file", output_file]
        if task_duration_s is not None:
            cmd += ["--duration", str(task_duration_s)]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)

        # Parse confidence from output
        score = 0.5
        bucket = "medium"
        factors = []
        for line in result.stdout.split("\n"):
            if line.startswith("Confidence:"):
                parts = line.split()
                score = float(parts[1])
                bucket = parts[2].strip("[]")
            elif line.strip().startswith("-") or (line.startswith("  ") and ":" in line and not line.strip().startswith("Confidence")):
                factors.append(line.strip())

        return {"score": score, "bucket": bucket, "factors": factors}

    except (subprocess.TimeoutExpired, OSError, FileNotFoundError, ValueError):
        return {"score": 0.5, "bucket": "medium", "factors": ["confidence engine unavailable"]}


def determine_outcome(exit_code: int, success_criteria: str,
                      output_file: str | None, exceptional: bool,
                      task_duration_s: float | None) -> dict:
    """
    Determine outcome with confidence scoring.

    Returns:
    - score: 0.0-1.0 confidence
    - bucket: high|medium|low|very_low
    - status: PASS | LOW_CONFIDENCE | FAIL
    - flagged: True if needs human review
    """
    conf = get_confidence(exit_code, success_criteria, output_file, task_duration_s)
    score = conf["score"]

    result = {
        "exit_code": exit_code,
        "success_criteria": success_criteria,
        "exceptional": exceptional,
        "confidence_score": score,
        "confidence_bucket": conf["bucket"],
        "confidence_factors": conf["factors"],
        "status": "PASS",
        "flagged": False,
        "rationale": "",
    }

    # Determine status and flagging
    if score < FAIL_THRESHOLD:
        result["status"] = "FAIL"
        result["rationale"] = (
            f"Confidence score {score:.2f} below fail threshold {FAIL_THRESHOLD}. "
            f"Exit code: {exit_code}. "
            f"Factors: {'; '.join(conf['factors'][:3])}"
        )
        result["failure_type"] = "LOW_CONFIDENCE"
    elif score < FLAG_THRESHOLD:
        result["status"] = "LOW_CONFIDENCE"
        result["flagged"] = True
        result["rationale"] = (
            f"Confidence score {score:.2f} below flag threshold {FLAG_THRESHOLD}. "
            f"Exit code: {exit_code}. "
            f"Factors: {'; '.join(conf['factors'][:3])}"
        )
        result["failure_type"] = "LOW_CONFIDENCE"
    elif exit_code != 0:
        # High confidence but non-zero exit = structural fail
        result["status"] = "FAIL"
        result["rationale"] = f"Exit code {exit_code} with confidence {score:.2f}"
        result["failure_type"] = "LOGIC"
    else:
        # PASS
        reasons = [f"Confidence score {score:.2f} [{conf['bucket']}]"]
        if output_file and os.path.exists(os.path.expanduser(output_file)):
            reasons.append(f"Output file exists: {output_file}")
        reasons.append(f"Exit code {exit_code}")
        result["rationale"] = "; ".join(reasons)

    return result


def handle_fail(eval_result: dict, task_id: str):
    """On FAIL or LOW_CONFIDENCE: reflect + add policy."""
    label = "FAIL" if eval_result["status"] == "FAIL" else "LOW_CONFIDENCE"
    print(f"\n  ❌ {label} for task '{task_id}'")
    print(f"     Confidence: {eval_result['confidence_score']:.2f}")
    print(f"     Rationale: {eval_result['rationale']}")

    if eval_result["status"] == "LOW_CONFIDENCE":
        print(f"  → Flagged for review (confidence below {FLAG_THRESHOLD})")
        print(f"  → No auto-policy added — human review needed first")
        return False

    # Step 1: Reflection
    print("  → Running post-failure reflection...")
    try:
        ref_script = HERMES_HOME / "scripts" / "reflect-on-correction.py"
        if ref_script.exists():
            r = subprocess.run(
                [sys.executable, str(ref_script)],
                capture_output=True, text=True, timeout=30
            )
            if r.returncode == 0:
                print(f"    ✅ Reflection: {r.stdout.strip()[:100]}")
            else:
                print(f"    ⚠️ Reflection warning: {r.stderr.strip()[:100]}")
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"    ⚠️ Reflection error: {e}")

    # Step 2: Add policy (only for structural FAIL, not LOW_CONFIDENCE)
    print("  → Adding failure policy...")
    trigger = eval_result["rationale"][:80]
    rule = (
        f"When outcome evaluator detects failure (exit code {eval_result['exit_code']}): "
        f"{eval_result['success_criteria'][:80]}. "
        f"Confidence: {eval_result['confidence_score']:.2f}. "
        f"Failure type: {eval_result.get('failure_type', 'unknown')}."
    )
    try:
        learn_script = HERMES_HOME / "scripts" / "otto-learn.py"
        if learn_script.exists():
            r = subprocess.run(
                [sys.executable, str(learn_script), "add", trigger, rule,
                 "--source", f"auto-detected failure: {task_id}"],
                capture_output=True, text=True, timeout=30
            )
            if r.returncode == 0:
                print(f"    ✅ Policy added: {r.stdout.strip()}")
            else:
                print(f"    ⚠️ Policy add warning: {r.stderr.strip()[:100]}")
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"    ⚠️ Policy add error: {e}")

    return False


def handle_pass(eval_result: dict, task_id: str):
    """On PASS: capture positive policy if exceptional."""
    print(f"\n  ✅ PASS for task '{task_id}' (confidence: {eval_result['confidence_score']:.2f})")

    if eval_result.get("exceptional") and eval_result["confidence_score"] >= HIGH_CONFIDENCE:
        print("  → Task was exceptional — capturing positive policy...")
        trigger = f"High-confidence success: {eval_result['success_criteria'][:80]}"
        rule = (
            f"Positive reinforcement: {eval_result['rationale']}. "
            f"Confidence: {eval_result['confidence_score']:.2f}. "
            "This pattern worked well and should be repeated."
        )
        try:
            learn_script = HERMES_HOME / "scripts" / "otto-learn.py"
            if learn_script.exists():
                r = subprocess.run(
                    [sys.executable, str(learn_script), "add", trigger, rule,
                     "--source", f"auto-detected success: {task_id}"],
                    capture_output=True, text=True, timeout=30
                )
                if r.returncode == 0:
                    print(f"    ✅ Positive policy added: {r.stdout.strip()}")
                else:
                    print(f"    ⚠️ Policy add warning: {r.stderr.strip()[:100]}")
        except (subprocess.TimeoutExpired, OSError) as e:
            print(f"    ⚠️ Policy add error: {e}")
    else:
        print("  → Task passed (not exceptional or below high-confidence threshold).")

    return True


def handle_low_confidence(eval_result: dict, task_id: str):
    """On LOW_CONFIDENCE: flag for review, no auto-action."""
    print(f"\n  ⚠️ LOW CONFIDENCE for task '{task_id}'")
    print(f"     Score: {eval_result['confidence_score']:.2f}")
    print(f"     Factors: {'; '.join(eval_result.get('confidence_factors', [])[:3])}")
    print(f"     Flagged for human review — no policy added.")
    return True


def main():
    parser = argparse.ArgumentParser(description="F2 Outcome Evaluator")
    parser.add_argument("--task-id", required=True, help="Task identifier")
    parser.add_argument("--exit-code", type=int, required=True, help="Task exit code")
    parser.add_argument("--success-criteria", required=True, help="Expected success criteria")
    parser.add_argument("--output-file", help="Expected output file path")
    parser.add_argument("--duration", type=float, help="Task duration in seconds")
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
        task_duration_s=args.duration,
    )

    log_injection(args.task_id, eval_result)

    if eval_result["status"] == "FAIL":
        handle_fail(eval_result, args.task_id)
    elif eval_result["status"] == "LOW_CONFIDENCE":
        handle_low_confidence(eval_result, args.task_id)
    else:
        handle_pass(eval_result, args.task_id)

    if args.verbose:
        print(f"\n--- Full Evaluation ---")
        print(json.dumps(eval_result, indent=2))

    print()
    return 0 if eval_result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
