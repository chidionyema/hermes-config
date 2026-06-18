#!/usr/bin/env python3
"""
Policy enforcer — runtime guard.

Called BEFORE every significant action (ask, dispatch, delegate, kill, wait).
Blocks actions that are status-check questions about things the system can verify directly.

Structural fix for: asking the user "is this operational?" instead of running the tests.
The answer to "is it working" is always "run it and find out" — so that's what this does.
"""

import json
import os
import re
import sys
from datetime import datetime

HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
POLICY_DIR = os.path.join(HERMES_HOME, "policies")
FIRINGS_LOG = os.path.join(HERMES_HOME, "logs", "policy-firings.jsonl")

# Question-starting words — any action that starts with these is a question
QUESTION_STARTERS = [
    "is ", "are ", "can ", "could ", "would ", "should ", "shall ", "will ",
    "do ", "does ", "did ", "has ", "have ", "had ", "was ", "were ", "may ",
    "might ", "am ", "what ", "when ", "where ", "which ", "who ", "how ",
]

# If the action contains these, it's a request for permission or input, not information
PERMISSION_MARKERS = [
    "should i", "want me to", "shall i", "up to you", "your call",
    "let me know if", "thoughts?", "what approach", "what option",
    "you want me to", "would you like me to",
    "awaiting", "pending your", "pending input", "pending feedback", "pending thoughts",
]

# But if the question is asking about something verifiable, it should be an action not a question
VERIFIABLE_PREFIXES = [
    "is this ", "is it ", "is the ", "is my ", "is your ",
    "are they ", "are these ", "are those ", "are we ", "are you ",
    "are the ",
    "can you check", "can i check", "can it ",
    "has the ", "have the ",
]

# Readiness keywords that indicate a verifiable status question
VERIFIABLE_KEYWORDS = [
    "operational", "working", "ready", "live", "active", "deploy", "done",
    "finished", "complete", "passing", "green", "good", "running", "healthy",
    "online", "up ", "accessible", "verified", "valid", "fixed",
    "still", "yet", "already", "now ",
]

def check_action(action_text: str) -> list:
    """
    Check action against the single structural rule:
    If it's a question about something verifiable → BLOCKED
    """
    action_lower = action_text.strip().lower()
    violations = []
    
    # Check if it's a question (starts with a question word)
    is_question = any(action_lower.startswith(s) for s in QUESTION_STARTERS)
    
    if is_question:
        # Check if it's about something verifiable (prefix + keyword required)
        is_verifiable = any(action_lower.startswith(p) for p in VERIFIABLE_PREFIXES) and any(k in action_lower for k in VERIFIABLE_KEYWORDS)
        is_permission = any(m in action_lower for m in PERMISSION_MARKERS)
        
        if is_verifiable:
            violations.append({
                "policy_id": "pol-20260618-007",
                "reason": "Asked about status of something verifiable. Run the check instead.",
                "rule": "If asking about whether something works/runs/is ready, execute the verification script and report the result. Never ask if it's operational — run the checks."
            })
        elif is_permission:
            violations.append({
                "policy_id": "pol-20260618-007",
                "reason": "Asked permission instead of executing.",
                "rule": "If the work is clearly defined, within scope, and doesn't touch money/identity/moat → execute immediately."
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
    """Returns 0 if safe, 1 if blocked."""
    violations = check_action(action_text)
    
    if not violations:
        print("PASS")
        return 0
    
    for v in violations:
        pid = v["policy_id"]
        rule = v["rule"]
        fire_policy(pid, v.get("reason", pid), rule, context=action_text[:200])
        print(f"BLOCKED by {pid}: {v.get('reason', 'No reason')}")
        print(f"  Rule: {rule[:120]}")
    
    return 1


if __name__ == "__main__":
    action = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else sys.stdin.read().strip()
    if not action:
        print("PASS (no action to check)")
        sys.exit(0)
    sys.exit(enforce(action))
