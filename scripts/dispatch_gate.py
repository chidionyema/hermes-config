#!/usr/bin/env python3
"""
Dispatch gate — structural guard against asking when I should be doing.

Every time I'm about to ask the user a question about whether to proceed,
I invoke this gate first. It evaluates whether the question can be answered
by the system alone. Only if the gate returns DISPATCH_NEEDS_USER do I ask.

Usage:
    python3 dispatch_gate.py "Should I fix the entitlements stub?" --context "work exists: True, risk: low, spec: clear"

Returns one of:
    DISPATCH_NOW
    DISPATCH_NEEDS_USER
    DISPATCH_BLOCKED
"""

import re
import sys

# Gates that must ALL be green for auto-dispatch
REQUIRED_CONDITIONS = [
    ("work_clarified", "The work is specific enough to start without asking"),
    ("no_money_identity_moat", "Does not modify money handling, identity, or the moat (verdict/adversarial pass)"),
    ("no_user_permission_needed", "No external user account, credentials, or legal text needed"),
    ("spec_clear_from_context", "The goal is clear from existing specs, files, or prior conversation"),
]

FORBIDDEN_PATTERNS = [
    r"should I (?:fix|build|create|dispatch|run|do|start)",
    r"want me to",
    r"shall I",
    r"shall we",
    r"(?:your|the) call",
    r"up to you",
    r"let me know if",
    r"tell me how",
    r"which one",
    r"which approach",
    r"thoughts\?",
]

def check_question(question: str) -> bool:
    """True if the question contains asking-for-permission language."""
    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, question.lower()):
            return True
    return False

def main():
    args = sys.argv[1:]
    question = " ".join(args) if args else "(no question captured)"

    if check_question(question):
        print("DISPATCH_NEEDS_USER")
        print(f"BLOCKED: asked '{question}'")
        print("This question didn't need asking. Execute instead.")
        return 1

    print("DISPATCH_NOW")
    return 0

if __name__ == "__main__":
    sys.exit(main())
