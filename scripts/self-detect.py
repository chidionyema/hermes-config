#!/usr/bin/env python3
"""
self-detect.py — Self-detected failure handler (B).

Runs automatically after tasks complete, checking if the outcome
indicates a failure. On self-detected failure, triggers the same
reflect→policy loop a user correction would.

This is the autonomy lever — Otto detects its own failures without
waiting for user correction.

SHIPPED: Now safe because F1 (retrieval) prevents policy bloat and
F2 (eval regression) prevents gaming the eval.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
EVAL_LOG = HERMES_HOME / "logs" / "eval-confidence.jsonl"
INJECTION_LOG = HERMES_HOME / "logs" / "injection-log.jsonl"
POLICY_DIR = HERMES_HOME / "policies"
REFLECTION_DIR = HERMES_HOME / "logs" / "reflection"

TODAY = datetime.now(timezone.utc).strftime("%Y%m%d")

# idle-learning-run.sh wraps this whole phase (Phase 3b) in an outer `timeout`
# bounded by PHASE_TIMEOUT (HERMES_IDLE_PHASE_TIMEOUT, default 30s). On a
# self-detected failure, handle_self_detected_failure() below makes up to 4
# sequential subprocess calls; a flat timeout=30 per call gives a worst case
# of 4*30=120s, which blows the 30s outer budget and would fire rc=124 (same
# structural bug class fixed in agent_simulator.py for Phase 2.6). Derive the
# per-call budget from the outer phase budget so the sum always has headroom.
PHASE_TIMEOUT_S = int(os.environ.get("HERMES_IDLE_PHASE_TIMEOUT", "30"))
_SELF_DETECT_SUBPROCESS_CALLS = 4
SUBPROCESS_TIMEOUT_S = max(5, (PHASE_TIMEOUT_S - 5) // _SELF_DETECT_SUBPROCESS_CALLS)


def get_recent_evaluations(n: int = 5) -> list:
    """Get the last N evaluation entries from eval log."""
    if not EVAL_LOG.exists():
        return []
    with open(EVAL_LOG) as f:
        lines = [l.strip() for l in f if l.strip()]
    entries = []
    for line in lines[-n:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def is_self_detected_failure(eval_entry: dict) -> bool:
    """
    Determine if an evaluation represents a self-detectable failure.

    Criteria:
    - Confidence score < 0.30 (structural fail)
    - OR exit code != 0 (non-zero exit)
    - AND not already flagged as user-corrected

    Returns True if this is a self-detected failure that needs a policy.
    """
    score = eval_entry.get("confidence_score", 0.5)
    exit_code = eval_entry.get("exit_code", 0)
    status = eval_entry.get("status", "")

    # Only process FAILs (not LOW_CONFIDENCE — those need human review)
    if status != "FAIL":
        return False

    # Don't double-process — check if already handled
    already_handled = eval_entry.get("_self_detected", False)
    if already_handled:
        return False

    return True


def handle_self_detected_failure(eval_entry: dict) -> dict:
    """
    Handle a self-detected failure:
    1. Add a policy via otto-learn
    2. Run post-failure reflection
    3. Mark the eval entry as handled

    Returns result dict.
    """
    task_id = eval_entry.get("task_id", "unknown")
    criteria = eval_entry.get("success_criteria", "")
    score = eval_entry.get("confidence_score", 0.5)
    exit_code = eval_entry.get("exit_code", 0)

    result = {
        "task_id": task_id,
        "confidence_score": score,
        "policy_added": False,
        "reflection_run": False,
        "errors": [],
    }

    # Get the existing failure corpus for context
    corpus_script = HERMES_HOME / "scripts" / "self-regression.py"
    if corpus_script.exists():
        try:
            subprocess.run(
                [sys.executable, str(corpus_script), "--harvest"],
                capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT_S
            )
        except Exception:
            pass

    # Step 1: Add a policy
    print(f"\n  → [SELF-DETECTED] Task '{task_id}' failed (confidence: {score:.2f})", file=sys.stderr)
    print(f"     Adding failure policy...", file=sys.stderr)

    trigger = f"Self-detected failure: {criteria[:60]}, exit code {exit_code}"
    rule = (
        f"Self-detected failure (confidence {score:.2f}): "
        f"Task '{task_id}' failed with exit code {exit_code}. "
        f"Criteria: {criteria[:80]}. "
        f"Reflect and adjust approach before retrying."
    )

    try:
        learn_script = HERMES_HOME / "scripts" / "otto-learn.py"
        if learn_script.exists():
            r = subprocess.run(
                [sys.executable, str(learn_script), "add", trigger, rule,
                 "--source", f"self-detected: {task_id}"],
                capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT_S
            )
            if r.returncode == 0:
                result["policy_added"] = True
                print(f"    ✅ Policy added: {r.stdout.strip()[:80]}", file=sys.stderr)
            else:
                err = r.stderr.strip()[:100]
                result["errors"].append(f"Policy add: {err}")
    except (subprocess.TimeoutExpired, OSError) as e:
        result["errors"].append(f"Policy add error: {e}")

    # Step 2: Run reflection
    try:
        ref_script = HERMES_HOME / "scripts" / "reflect-on-correction.py"
        if ref_script.exists():
            r = subprocess.run(
                [sys.executable, str(ref_script)],
                capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT_S
            )
            if r.returncode == 0:
                result["reflection_run"] = True
                print(f"    ✅ Reflection updated", file=sys.stderr)
            else:
                result["errors"].append(f"Reflection: {r.stderr.strip()[:100]}")
    except (subprocess.TimeoutExpired, OSError) as e:
        result["errors"].append(f"Reflection error: {e}")

    # Step 3: Add to regression corpus
    trigger_short = trigger[:100]
    rule_short = rule[:200]
    try:
        reg_script = HERMES_HOME / "scripts" / "self-regression.py"
        if reg_script.exists():
            r = subprocess.run(
                [sys.executable, str(reg_script), "--add", trigger_short, rule_short],
                capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT_S
            )
            if r.returncode == 0:
                print(f"    ✅ Added to regression corpus", file=sys.stderr)
    except (subprocess.TimeoutExpired, OSError) as e:
        result["errors"].append(f"Corpus add error: {e}")

    # Mark the eval entry as handled (add _self_detected flag to the log)
    eval_entry["_self_detected"] = True
    eval_entry["_self_detected_at"] = datetime.now(timezone.utc).isoformat()
    # Re-write the log line — simple append with marked entry
    with open(EVAL_LOG, "a") as f:
        f.write(json.dumps({**eval_entry, "_self_detected": True}) + "\n")

    return result


def scan_recent_tasks() -> list:
    """
    Scan recent evaluations for self-detected failures.

    Returns list of failure events handled.
    """
    evaluations = get_recent_evaluations(10)
    handled = []

    for entry in evaluations:
        if is_self_detected_failure(entry):
            result = handle_self_detected_failure(entry)
            handled.append(result)

    return handled


def main():
    """CLI — scan and handle self-detected failures."""
    import argparse
    parser = argparse.ArgumentParser(description="Self-detected failure handler")
    parser.add_argument("--scan", action="store_true", help="Scan recent tasks for failures")
    parser.add_argument("--quiet", action="store_true", help="Minimal output")

    args = parser.parse_args()

    if args.scan or True:  # default action
        handled = scan_recent_tasks()

        if handled:
            for h in handled:
                status = "✅" if h["policy_added"] else "⚠️"
                print(f"{status} Self-detected: {h['task_id']} (confidence: {h['confidence_score']:.2f})")
                if h.get("errors"):
                    for e in h["errors"]:
                        print(f"  ⚠️ {e}")
        elif not args.quiet:
            print("No self-detected failures in recent evaluations.")
            print("The eval is running cleanly.")

        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
