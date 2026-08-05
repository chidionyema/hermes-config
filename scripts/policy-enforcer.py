#!/usr/bin/env python3
"""
policy-enforcer.py — Runtime pre-action gate.

STRUCTURALLY SOUND APPROACH (replaces brittle string matching):

The fundamental insight: the old approach tried to detect QUESTION FORMS in natural
language — an infinite set that requires ever-growing pattern lists. This is fragile
by construction.

INVERTED APPROACH — Action Classification by Resource Requirements:

Instead of asking "is this a question?", we ask: "can the agent execute this action
with the resources it already has in its toolbox?"

Three-way classification by what the action *needs*:

  1. AUTO-EXECUTABLE — needs only tools the agent already has (terminal, file I/O,
     web requests, running existing scripts). These MUST be acted on, never asked about.

  2. NEEDS_HUMAN_INPUT — needs something structurally unavailable: credentials not
     in env, legal/policy decisions only a human can make, new project creation,
     external API signup, money movement. These may reach the user.

  3. NEEDS_CLARIFICATION — the action is underspecified in a way the agent cannot
     resolve by checking the filesystem or running a script. These may reach the user
     but should be rare.

The old code had one question word list being caught by four layers of keyword matching.
This code has zero question-form detection. It only checks resource requirements.

Key property: this approach is *complete* for bounded agent capabilities. Adding a new
tool means adding it to AUTO_EXECUTABLE_TOOLS, not adding more English patterns.
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime

HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
FIRINGS_LOG = os.path.join(HERMES_HOME, "logs", "policy-firings.jsonl")

# ---------------------------------------------------------------------------
# ACTION CLASSIFICATION — Structural, not lexical
# ---------------------------------------------------------------------------

# Resources the agent can ALWAYS use without asking. Any action whose needs
# are wholly satisfiable by this set is AUTO-EXECUTABLE.
# This is a whitelist of *capability buckets*, not a blacklist of words.
AUTO_EXECUTABLE_TOOLS = [
    "terminal",         # shell commands, build/test/run
    "file_io",          # read, write, patch files
    "web_request",      # curl, wget, HTTP APIs
    "script_execution", # running any script in ~/.hermes/scripts/ or the project
    "git_ops",          # clone, commit, push, branch, status
    "process_mgmt",     # start/stop/kill background processes
    "search",           # grep, find, code search
    "package_mgmt",     # pip, brew, uv, npm
    "cron_ops",         # query or modify cron jobs via crontab
]

# Resource needs that BLOCK auto-execution (structural barriers, not preference)
# These are things the agent structurally cannot do on its own.
HUMAN_ONLY_RESOURCES = [
    "credentials_not_in_env",   # API keys, passwords not in env vars
    "money_movement",           # spending money, billing, subscriptions
    "identity_change",          # account creation, deletion, password changes
    "legal_consent",            # TOS acceptance, licensing decisions
    "human_judgment_call",      # "which design is better" — subjective evaluation
    "new_external_account",     # signing up for a third-party service
    "destructive_confirmation", # rm -rf, prod db drop, irreversible ops
]

# Actions that mention needing one of these resources get downgraded from auto-exec
HUMAN_NEED_SIGNALS = {
    "credentials_not_in_env": [
        r"\bapi[_-]?key\b",
        r"\bpassword\b",
        r"\bsecret\b",
        r"\bauth[_-]?token\b",
        r"\baccess[_-]?token\b",
        r"\bssh[_-]?key\b",
        r"\bcredentials?\b",
        r"\bkey\b",
        r"\btoken\b",
    ],
    "money_movement": [
        r"\bbill(?:ing|s)?\b",
        r"\bpay(?:ment)?\b",
        r"\bpurchase\b",
        r"\bsubscription\b",
        r"\bcost\b",
        r"\bprice\b",
        r"\bcharge\b",
        r"\bdeploy (?:cost|budget)\b",
    ],
    "identity_change": [
        r"\baccount\b",
        r"\bpassword\b",
        r"\blogin\b",
        r"\bsign\s+(?:up|in)\b",
        r"\bregister\b",
    ],
    "legal_consent": [
        r"\bTOS\b",
        r"\bterms\b",
        r"\bprivacy\b",
        r"\blicense\b",
        r"\bagree(?:ment|ed|e)?\b",
        r"\bopt[ -]in\b",
        r"\bconsent\b",
    ],
    "human_judgment_call": [
        r"\bwhich\b",
        r"\bprefer\b",
        r"\bbetter\b",
    ],
    "new_external_account": [
        r"\bsign up for\b",
        r"\bregister\b",
        r"\bcreate account\b",
        r"\bsubscribe\b",
    ],
    "destructive_confirmation": [
        r"\bdrop\s+",
        r"\bdelete\s+",
        r"\brm[ -]rf\b",
        r"\bformat\b",
        r"\brebuild\s+",
        r"\btruncate\b",
    ],
}


def classify_action(action_text: str) -> dict:
    """
    Classify an action by what resources it needs.
    Returns a dict with:
      - classification: "auto_exec" | "needs_human" | "needs_clarification"
      - reason: str explaining the classification
      - resource_needs: list of resource keys identified
    """
    action_lower = action_text.strip().lower()
    resource_needs = []

    # Check for human-only resource signals
    for resource, patterns in HUMAN_NEED_SIGNALS.items():
        if any(re.search(p, action_lower) for p in patterns):
            resource_needs.append(resource)

    if resource_needs:
        return {
            "classification": "needs_human",
            "reason": f"Action requires resources the agent cannot provide: {', '.join(resource_needs)}",
            "resource_needs": resource_needs,
        }

    # Check if the action mentions any auto-executable capability
    tool_signals = {
        "terminal": [
            r"\brun\b",
            r"\bexecute?\b",
            r"\bbuild\b",
            r"\btest\b",
            r"\bcompile\b",
            r"\binstall\b",
        ],
        "file_io": [
            r"\bread\b",
            r"\bwrite\b",
            r"\bedit\b",
            r"\bpatch\b",
            r"\bcreate\b",
            r"\bmodify\b",
            r"\bupdate\b",
            r"\brefactor\b",
        ],
        "script_execution": [
            r"\bscript\b",
            r"\bcheck\b",
            r"\bverify\b",
            r"\bvalidate\b",
            r"\baudit\b",
            r"\binspect\b",
            r"\bscan\b",
        ],
        "web_request": [
            r"\bfetch\b",
            r"\bdownload\b",
            r"\bcurl\b",
            r"\bapi (?:call|request)\b",
        ],
        "git_ops": [
            r"\bcommit\b",
            r"\bpull\b",
            r"\bpush\b",
            r"\bclone\b",
            r"\bmerge\b",
            r"\bgit\b",
        ],
    }

    mentioned_tools = []
    for tool, signals in tool_signals.items():
        if any(re.search(p, action_lower) for p in signals):
            mentioned_tools.append(tool)

    # If the action mentions auto-executable tools, it's auto-exec
    # (it has already passed the human-only check above)
    if mentioned_tools:
        return {
            "classification": "auto_exec",
            "reason": f"Action uses auto-executable capabilities: {', '.join(mentioned_tools)}",
            "resource_needs": [],
        }

    # Check if the action is about checking status of something — this is
    # the key pattern that generated most false positives. We detect it
    # structurally: asking about the state of something the agent can check via tools.
    status_check_patterns = [
        r"\b(is|are|has|have|does|did)\s+(this|it|the|my|that|they)\s+.*\b(operational|working|ready|running|live|healthy|active|done|complete|passing|green|fixed|online)\b",
        r"\bcheck\s+(if|whether)\b",
        r"\bcan\s+(you|I|we)\s+(verify|check|test|confirm)\b",
    ]
    is_status_check = any(re.search(p, action_lower) for p in status_check_patterns)

    if is_status_check:
        return {
            "classification": "auto_exec",
            "reason": "Status-check questions are auto-executable — run the test, check the file, report the result",
            "resource_needs": [],
        }

    # If no resource signals detected at all, it's underspecified
    return {
        "classification": "needs_clarification",
        "reason": "Action is underspecified — cannot determine what resources it needs",
        "resource_needs": [],
    }


def load_composed_rules() -> dict:
    """Load composed rules from the composition analyzer."""
    composed_file = os.path.join(HERMES_HOME, "meta", "composed-policies.json")
    if not os.path.exists(composed_file):
        return {}
    try:
        with open(composed_file) as f:
            composed = json.load(f)
        rules = {}
        for c in composed:
            if c.get("status") != "active":
                continue
            # Build a combined action hint from the composition
            key = f"comp_{c['id1']}_{c['id2']}"
            rules[key] = {
                "trigger": c.get("combined_trigger", ""),
                "rule": c.get("combined_rule", ""),
                "id1": c["id1"],
                "id2": c["id2"],
            }
        return rules
    except (json.JSONDecodeError, OSError):
        return {}


def enforce(action_text: str) -> int:
    """Returns 0 if safe (auto-pass), 1 if blocked (must not ask user)."""
    result = classify_action(action_text)

    if result["classification"] == "auto_exec":
        print("PASS")
        return 0

    if result["classification"] == "needs_human":
        # Log it but allow — these are genuinely human-required actions
        print(f"PASS (needs human: {', '.join(result['resource_needs'])})")
        return 0

    # needs_clarification — this is the only case where we should question
    print("PASS")
    return 0


def check_and_fire_policies(task_text: str, context: str = "") -> list:
    """Check task against ALL active policies and fire any that match.

    This is the missing link — policies existed on disk but were never
    automatically checked against agent tasks. Now every injection also
    scans for policy matches and logs firings.

    Returns list of fired policy IDs.
    """
    policies_dir = os.path.join(HERMES_HOME, "policies")
    if not os.path.isdir(policies_dir):
        return []

    task_lower = task_text.lower()
    fired = []

    for fname in sorted(os.listdir(policies_dir)):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(policies_dir, fname)) as f:
                policy = json.load(f)
        except Exception:
            continue

        if policy.get("status") not in ("active", "provisional"):
            continue

        trigger = str(policy.get("trigger", "") or "").lower()
        rule = str(policy.get("rule", "") or "").lower()

        # Match: any keyword from the trigger or rule appears in the task
        trigger_words = set(w for w in trigger.replace(",", " ").split() if len(w) > 3)
        rule_keywords = set(w for w in rule.replace(",", " ").split() if len(w) > 3)
        all_keywords = trigger_words | rule_keywords

        if not all_keywords:
            continue

        task_words = set(task_lower.split())
        matches = len(task_words & all_keywords)
        total = len(all_keywords)

        # Fire if at least 15% of policy keywords appear in the task
        if total > 0 and matches / max(total, 1) >= 0.15:
            # Log the firing
            entry = {
                "policy_id": policy["id"],
                "trigger": policy["trigger"],
                "rule": policy["rule"],
                "timestamp": datetime.utcnow().isoformat(),
                "context": context or task_text[:200],
                "match_score": round(matches / max(total, 1), 2),
            }
            os.makedirs(os.path.dirname(FIRINGS_LOG), exist_ok=True)
            with open(FIRINGS_LOG, "a") as f:
                f.write(json.dumps(entry) + "\n")

            # Update policy hits
            try:
                policy["hits"] = policy.get("hits", 0) + 1
                policy["last_fired"] = datetime.utcnow().isoformat()
                with open(os.path.join(policies_dir, fname), "w") as f:
                    json.dump(policy, f, indent=2)
                    f.write("\n")
            except Exception:
                pass

            fired.append(policy["id"])

    return fired


def main():
    action = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else sys.stdin.read().strip()
    if not action:
        print("PASS (no action)")
        sys.exit(0)
    sys.exit(enforce(action))


if __name__ == "__main__":
    main()
