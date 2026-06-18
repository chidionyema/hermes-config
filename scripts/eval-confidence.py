"""
F2 — Eval confidence scoring + divergence detection for Otto.

Replaces binary PASS/FAIL with a calibrated confidence spectrum.
Divergence detection is PASSIVE — uses user corrections as the
human-grade holdout. No extra work for the user.

Architecture:
- Confidence scoring: 0.0-1.0 based on signal quality (exit code, output file,
  criteria specificity, past accuracy on similar tasks)
- Divergence detection: when user corrects Otto on a task Otto self-graded PASS,
  that's a divergence event. Track drift rate.
- Holdout corpus: built passively from correction events, not manual grading.
- Eval health: silent unless drift rate exceeds threshold.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
EVAL_LOG = HERMES_HOME / "logs" / "eval-confidence.jsonl"
DIVERGENCE_LOG = HERMES_HOME / "logs" / "eval-divergence.jsonl"
HOLDOUT_FILE = HERMES_HOME / "logs" / "eval-holdout.json"

ISO_NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- Confidence scoring ---

def score_confidence(exit_code: int, success_criteria: str,
                     output_file: Optional[str] = None,
                     task_duration_s: Optional[float] = None) -> dict:
    """
    Score confidence in a task outcome (0.0-1.0).

    Factors:
    - Exit code: 0 → high confidence, non-zero → degraded
    - Criteria specificity: vague criteria → lower confidence
    - Output file: expected file missing → signal quality issue
    - Duration: extremely fast or slow → lower confidence
    - Past accuracy on similar tasks (from divergence log)

    Returns dict with score, factors, and rationale.
    """
    reasons = []
    score = 0.5  # neutral baseline

    # Factor 1: Exit code quality
    if exit_code == 0:
        score += 0.25
        reasons.append("exit_code: +0.25 (zero)")
    elif exit_code == 1:
        score -= 0.1
        reasons.append("exit_code: -0.10 (non-zero)")
    elif exit_code < 0:
        score -= 0.2
        reasons.append(f"exit_code: -0.20 (signal {exit_code})")
    else:
        score -= 0.15
        reasons.append(f"exit_code: -0.15 (code {exit_code})")

    # Factor 2: Criteria specificity
    criteria_lower = (success_criteria or "").lower()
    specificity_keywords = ["must", "should", "expected", "exact", "exactly",
                            "all", "every", "none", "not", "assert", "verify"]
    vague_keywords = ["better", "good", "nice", "improve", "try", "maybe",
                      "look", "seems", "check", "review"]

    specificity = sum(1 for kw in specificity_keywords if kw in criteria_lower)
    vagueness = sum(1 for kw in vague_keywords if kw in criteria_lower)

    spec_score = 0.0
    spec_score += min(0.1, specificity * 0.03)  # up to +0.1 for specificity
    spec_score -= min(0.15, vagueness * 0.05)   # up to -0.15 for vagueness

    # Length-based specificity heuristic
    word_count = len(criteria_lower.split())
    if word_count < 5:
        spec_score -= 0.1  # too brief to be specific
        reasons.append("criteria: -0.10 (too vague, <5 words)")
    elif word_count > 50:
        spec_score += 0.05  # detailed criteria
        reasons.append("criteria: +0.05 (detailed criteria)")

    if abs(spec_score) > 0.01:
        sign = "+" if spec_score > 0 else ""
        reasons.append(f"criteria: {sign}{spec_score:.2f}")
    score += spec_score

    # Factor 3: Output file check
    if output_file:
        if os.path.exists(os.path.expanduser(output_file)):
            score += 0.1
            reasons.append("output_file: +0.10 (exists)")
        else:
            score -= 0.15
            reasons.append("output_file: -0.15 (missing)")

    # Factor 4: Duration-based signal (if provided)
    if task_duration_s is not None:
        if task_duration_s < 0.5:
            score -= 0.05  # suspiciously fast
            reasons.append("duration: -0.05 (too fast, <0.5s)")
        elif task_duration_s > 300:
            score -= 0.05  # suspiciously slow
            reasons.append("duration: -0.05 (too slow, >5min)")

    # Clamp
    score = max(0.0, min(1.0, score))

    return {
        "score": round(score, 3),
        "factors": reasons,
        "confidence_bucket": _bucket(score),
    }


def _bucket(score: float) -> str:
    """Map score to a confidence bucket."""
    if score >= 0.85:
        return "high"
    elif score >= 0.60:
        return "medium"
    elif score >= 0.30:
        return "low"
    return "very_low"


# --- Divergence detection ---

def detect_divergence(task_id: str, otto_grade: dict, user_grade: dict) -> Optional[dict]:
    """
    Detect divergence between Otto's self-grade and a user's correction/grade.

    Called when the user corrects Otto on a task. If Otto had self-graded
    this task as PASS/high-confidence, divergence is flagged.

    Returns divergence event dict if significant, None otherwise.
    """
    otto_score = otto_grade.get("score", 0.5)
    user_score = user_grade.get("score", 0.0)

    divergence = otto_score - user_score

    # Only flag meaningful divergence
    if divergence < 0.3:
        return None

    event = {
        "timestamp": ISO_NOW,
        "task_id": task_id,
        "otto_score": otto_score,
        "user_score": user_score,
        "divergence": round(divergence, 3),
        "otto_bucket": _bucket(otto_score),
        "user_bucket": _bucket(user_score),
        "user_rationale": user_grade.get("rationale", ""),
    }

    # Log divergence
    os.makedirs(DIVERGENCE_LOG.parent, exist_ok=True)
    with open(DIVERGENCE_LOG, "a") as f:
        f.write(json.dumps(event) + "\n")

    # Update holdout corpus
    _update_holdout(task_id, otto_score, user_score)

    return event


def _update_holdout(task_id: str, otto_score: float, user_score: float):
    """Update the human-grade holdout corpus with this correction."""
    holdout = []
    if HOLDOUT_FILE.exists():
        with open(HOLDOUT_FILE) as f:
            try:
                holdout = json.load(f)
            except json.JSONDecodeError:
                holdout = []

    holdout.append({
        "task_id": task_id,
        "otto_score": otto_score,
        "user_score": user_score,
        "added_at": ISO_NOW,
    })

    # Keep last 50 entries
    holdout = holdout[-50:]

    os.makedirs(HOLDOUT_FILE.parent, exist_ok=True)
    with open(HOLDOUT_FILE, "w") as f:
        json.dump(holdout, f, indent=2)


def get_divergence_rate() -> dict:
    """
    Calculate divergence rate from logged events.

    Returns {rate, events_count, last_divergence, drift_detected}.
    Drift detected if >20% of recent evals (last 20) diverged significantly.
    """
    if not DIVERGENCE_LOG.exists():
        return {"rate": 0.0, "events": 0, "drift_detected": False}

    events = []
    with open(DIVERGENCE_LOG) as f:
        for line in f:
            if line.strip():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    recent = events[-20:]  # last 20 divergence checks
    significant = [e for e in recent if e.get("divergence", 0) >= 0.3]
    rate = len(significant) / max(len(recent), 1)

    return {
        "rate": round(rate, 3),
        "events": len(events),
        "recent_checks": len(recent),
        "significant_divergences": len(significant),
        "drift_detected": rate > 0.2 and len(recent) >= 5,  # need 5+ samples to call drift
        "last_divergence": events[-1]["timestamp"] if events else None,
    }


# --- Eval health ---

def get_eval_health() -> dict:
    """
    Evaluate overall eval health.

    Returns dict with:
    - status: healthy | warning | drift
    - holdout_size: number of human-graded samples
    - divergence_rate: latest rate
    - calibration_score: correlation between Otto scores and user scores
    - recommendation: what to do if unhealthy
    """
    holdout = []
    if HOLDOUT_FILE.exists():
        with open(HOLDOUT_FILE) as f:
            try:
                holdout = json.load(f)
            except json.JSONDecodeError:
                holdout = []

    drift = get_divergence_rate()

    health = {
        "holdout_size": len(holdout),
        "divergence_rate": drift["rate"],
        "drift_detected": drift["drift_detected"],
        "total_divergence_events": drift["events"],
        "calibration_score": None,
    }

    # Calibration: correlation between Otto scores and user scores
    if len(holdout) >= 3:
        otto_scores = [h["otto_score"] for h in holdout]
        user_scores = [h["user_score"] for h in holdout]
        try:
            # Simple mean absolute error as calibration metric
            mae = sum(abs(o - u) for o, u in zip(otto_scores, user_scores)) / len(holdout)
            health["calibration_score"] = round(1.0 - min(mae, 1.0), 3)
        except Exception:
            health["calibration_score"] = None

    # Status
    if drift["drift_detected"]:
        health["status"] = "drift"
        health["recommendation"] = (
            f"Divergence rate {drift['rate']:.0%} across {drift['recent_checks']} recent checks. "
            "Self-detection (B) should throttle until eval is re-tuned. "
            "Review recent divergence events and assess whether eval criteria "
            "need tightening."
        )
    elif len(holdout) < 5:
        if len(holdout) == 0:
            health["status"] = "seeding"
            health["recommendation"] = (
                "No human-graded corrections yet. The holdout corpus builds "
                "passively through corrections — no setup needed."
            )
        else:
            health["status"] = "building"
            health["recommendation"] = (
                f"{len(holdout)} correction(s) recorded. Need 5+ for calibration. "
                "Keep correcting as usual — each one adds to the holdout."
            )
    else:
        health["status"] = "healthy"
        health["recommendation"] = (
            "No significant drift detected. "
            f"{len(holdout)} holdout samples, {drift['rate']:.0%} divergence rate."
        )

    return health


# --- Logging ---

def log_evaluation(task_id: str, confidence_result: dict,
                   success_criteria: str, exit_code: int):
    """Log a confidence-scored evaluation to the eval log."""
    entry = {
        "timestamp": ISO_NOW,
        "task_id": task_id,
        "confidence_score": confidence_result["score"],
        "confidence_bucket": confidence_result["confidence_bucket"],
        "success_criteria": success_criteria[:200],
        "exit_code": exit_code,
        "factors": confidence_result["factors"],
    }
    os.makedirs(EVAL_LOG.parent, exist_ok=True)
    with open(EVAL_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


# --- CLI ---

def main():
    import argparse
    parser = argparse.ArgumentParser(description="F2 Eval Confidence & Divergence")
    parser.add_argument("--score", action="store_true", help="Score a task outcome")
    parser.add_argument("--exit-code", type=int, default=0, help="Task exit code")
    parser.add_argument("--success-criteria", default="", help="Success criteria")
    parser.add_argument("--output-file", help="Expected output file")
    parser.add_argument("--task-id", help="Task identifier")
    parser.add_argument("--duration", type=float, help="Task duration in seconds")
    parser.add_argument("--divergence", action="store_true",
                        help="Check divergence rate")
    parser.add_argument("--health", action="store_true", help="Eval health report")
    parser.add_argument("--record-user-grade", nargs=3,
                        metavar=("TASK_ID", "SCORE", "RATIONALE"),
                        help="Record a user's grade (e.g. from correction)")

    args = parser.parse_args()

    if args.divergence:
        drift = get_divergence_rate()
        print(json.dumps(drift, indent=2))
        return 0

    if args.health:
        health = get_eval_health()
        print(f"Eval Health: {health['status']}")
        print(f"  Holdout samples: {health['holdout_size']}")
        print(f"  Divergence rate: {health['divergence_rate']:.1%}")
        print(f"  Calibration: {health['calibration_score'] or 'N/A'}")
        print(f"  Drift: {'⚠️ DETECTED' if health['drift_detected'] else '✅ None'}")
        print(f"  {health['recommendation']}")
        return 0

    if args.record_user_grade:
        task_id, score_str, rationale = args.record_user_grade
        user_score = float(score_str)
        # Look up Otto's grade from eval log
        otto_score = 0.5  # default
        if EVAL_LOG.exists():
            with open(EVAL_LOG) as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        if entry.get("task_id") == task_id:
                            otto_score = entry.get("confidence_score", 0.5)
                            break
                    except json.JSONDecodeError:
                        continue

        user_grade = {"score": user_score, "rationale": rationale}
        otto_grade = {"score": otto_score}
        event = detect_divergence(task_id, otto_grade, user_grade)
        if event:
            print(f"Divergence detected: Otto {otto_score:.2f} vs User {user_score:.2f}")
            print(f"  Magnitude: {event['divergence']:.2f}")
        else:
            print(f"No significant divergence (Δ={abs(otto_score - user_score):.2f})")
        return 0

    if args.score:
        result = score_confidence(
            exit_code=args.exit_code,
            success_criteria=args.success_criteria,
            output_file=args.output_file,
            task_duration_s=args.duration,
        )
        if args.task_id:
            log_evaluation(args.task_id, result, args.success_criteria, args.exit_code)
        print(f"Confidence: {result['score']:.2f} [{result['confidence_bucket']}]")
        for f in result["factors"]:
            print(f"  {f}")
        return 0 if result["score"] >= 0.3 else 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    main()
