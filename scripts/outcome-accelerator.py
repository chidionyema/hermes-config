#!/usr/bin/env python3
"""Outcome Accelerator: logs every completed task as a mini-outcome record.
Feeds the outer-loop meta-improver with training data 10x faster.

Run by: task completion hook (calls task-state clear or after every tool batch)
"""
import json, os, sys
from datetime import datetime, timezone

HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
OUTCOME_LOG = os.path.join(HERMES_HOME, "meta", "change-outcomes.jsonl")
FIRINGS_LOG = os.path.join(HERMES_HOME, "logs", "policy-firings.jsonl")
SELF_LOG = os.path.join(HERMES_HOME, "logs", "outcomes", "task-outcomes.jsonl")

def iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def get_recent_firings(n=5):
    """Get the most recent policy firings to correlate with this task."""
    if not os.path.exists(FIRINGS_LOG):
        return []
    with open(FIRINGS_LOG) as f:
        lines = f.readlines()
    entries = []
    for line in lines[-n:]:
        try:
            entries.append(json.loads(line.strip()))
        except:
            continue
    return entries

def main():
    task_desc = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "completed"
    
    # Check if any policies fired recently → correlate
    recent = get_recent_firings(3)
    policies_used = list(set(f.get("policy_id", "?") for f in recent))
    
    # Determine outcome type
    if any("fix" in task_desc.lower() or "patch" in task_desc.lower() for _ in [1]):
        outcome_type = "fix"
    elif any("test" in task_desc.lower() or "verify" in task_desc.lower() for _ in [1]):
        outcome_type = "verification"
    elif any("create" in task_desc.lower() or "build" in task_desc.lower() for _ in [1]):
        outcome_type = "creation"
    elif any("investigat" in task_desc.lower() or "debug" in task_desc.lower() for _ in [1]):
        outcome_type = "investigation"
    elif any("improve" in task_desc.lower() or "accelerat" in task_desc.lower() for _ in [1]):
        outcome_type = "improvement"
    else:
        outcome_type = "general"
    
    record = {
        "change_id": f"outcome-auto-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "change_type": outcome_type,
        "description": task_desc[:200],
        "applied_at": iso_now(),
        "source": "task_outcome",
        "policies_fired": policies_used,
        "outcome": "pending",  # Will be re-evaluated during next idle-learning cycle
        "velocity_before": None,
        "velocity_after_N1": None,
        "velocity_after_N3": None,
    }
    
    os.makedirs(os.path.dirname(OUTCOME_LOG), exist_ok=True)
    os.makedirs(os.path.dirname(SELF_LOG), exist_ok=True)
    
    # Append to outcomes log (meta-improver reads this!)
    with open(OUTCOME_LOG, "a") as f:
        f.write(json.dumps(record) + "\n")
    
    # Also log to task-specific outcomes
    with open(SELF_LOG, "a") as f:
        f.write(json.dumps(record) + "\n")
    
    print(f"📊 Outcome logged: type={outcome_type} policies={policies_used}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
