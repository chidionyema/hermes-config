#!/usr/bin/env python3
"""
Policy enforcer — runtime guard that actually reads policies and blocks violations.

Called BEFORE every significant action (ask, dispatch, delegate, kill, wait).
Scans active policies and evaluates whether the current action violates any.

Installation: Add to SKILL.md's "Before every action" protocol.
"""

import json
import os
import re
import sys
from datetime import datetime

HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
POLICY_DIR = os.path.join(HERMES_HOME, "policies")
FIRINGS_LOG = os.path.join(HERMES_HOME, "logs", "policy-firings.jsonl")

# Pattern → policy_id mapping for fast matching
PATTERN_MAP = {
    r"\bshould\s+I\b": "pol-20260618-007",
    r"\bwant\s+me\s+to\b": "pol-20260618-007",
    r"\bshall\s+I\b": "pol-20260618-007",
    r"\bup\s+to\s+you\b": "pol-20260618-007",
    r"\byour\s+call\b": "pol-20260618-007",
    r"let\s+me\s+know\s+if": "pol-20260618-007",
    r"\bthoughts\s*\?": "pol-20260618-007",
    r"\bwhat\s+(?:approach|option)\b": "pol-20260618-007",
    r"\byou\s+want\s+me\s+to\b": "pol-20260618-007",
    r"would\s+you\s+like\s+me\s+to": "pol-20260618-007",
    r"\bawaiting\b": "pol-20260618-005",
    r"\bpending\s+(?:your\s+)?(?:decision|input|feedback|thoughts)\b": "pol-20260618-005",
    r"\bkilled?\s+(?:process|pytest|test\s+runner)": "pol-20260618-001",
    r"\bbackground\s*=\s*true\b": "pol-20260618-002",
    r"time\.sleep\b": "pol-20260618-002",
    r"\bI\s+(?:think|believe|guess)\s+(?:this|it)\s+(?:might|should|would)\b": "pol-20260618-006",
    r"\bIIUC\b": "pol-20260618-006",
    r"\bas\s+far\s+as\s+I\s+know\b": "pol-20260618-006",
    r"[Bb]earer\s+test-token": "pol-20260618-006",
}


def load_policies():
    """Load all policies with status=active or provisional."""
    if not os.path.isdir(POLICY_DIR):
        return []
    policies = []
    for fname in sorted(os.listdir(POLICY_DIR)):
        if fname.endswith(".json"):
            with open(os.path.join(POLICY_DIR, fname)) as f:
                policies.append(json.load(f))
    return policies


def check_action(action_text: str) -> list:
    """
    Check an action against all patterns.
    Returns list of violations: [{policy_id, trigger, rule, severity}]
    """
    violations = []
    action_lower = action_text.lower()
    
    # Quick pattern match
    for pattern, policy_id in PATTERN_MAP.items():
        if re.search(pattern, action_lower):
            violations.append({
                "policy_id": policy_id,
                "action_match": pattern,
                "reason": f"Action matches pattern '{pattern}'"
            })
    
    return violations


def fire_policy(policy_id, trigger, rule, context=""):
    """Log a policy firing."""
    os.makedirs(os.path.dirname(FIRINGS_LOG), exist_ok=True)
    entry = {
        "policy_id": policy_id,
        "trigger": trigger,
        "rule": rule[:200],
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "context": context[:200]
    }
    with open(FIRINGS_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


def enforce(action_text: str) -> int:
    """
    Main entry point.
    Returns 0 if safe to proceed, 1 if blocked by policy.
    Prints structured output.
    """
    violations = check_action(action_text)
    
    if not violations:
        print("PASS")
        return 0
    
    for v in violations:
        pid = v["policy_id"]
        # Load the policy for full details
        policy_path = os.path.join(POLICY_DIR, f"{pid}.json")
        trigger = pid
        rule = "See policy file"
        if os.path.exists(policy_path):
            with open(policy_path) as f:
                pdata = json.load(f)
                trigger = pdata.get("trigger", pid)
                rule = pdata.get("rule", rule)
        
        fire_policy(pid, trigger, rule, context=action_text[:200])
        print(f"BLOCKED by {pid}: {trigger}")
        print(f"  Rule violated: {rule[:120]}")
    
    return 1


if __name__ == "__main__":
    action = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else sys.stdin.read().strip()
    if not action:
        print("PASS (no action to check)")
        sys.exit(0)
    sys.exit(enforce(action))
