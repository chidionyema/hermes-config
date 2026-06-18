"""
F3 — Conflict Resolution Engine for Otto.

Addresses the third hardening bottleneck: when policy composition creates
contradictions, "specific overrides general" is the default — but only safe
if the specific policy's scope is correctly tight.

Architecture:
1. Scope analysis — checks that specific policies have correctly tight scope
   (e.g. "force-overwrite if temp full" must be scoped to "disk full" 
   conditions, not broad)
2. Contradiction detection — finds pairs of policies whose rules conflict
   (one says DO X, another says DON'T DO X for overlapping conditions)
3. Precedence resolution — specific-over-general with scope validation
4. Escalation — contradictory specifics with unclear scope get routed to
   strategist or user; no static rule resolves what it wasn't designed for

All conflicts are flagged with explicit rationale (auditable).
"""

import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Tuple

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
POLICY_DIR = HERMES_HOME / "policies"
COMPOSED_FILE = HERMES_HOME / "meta" / "composed-policies.json"
CONFLICTS_LOG = HERMES_HOME / "logs" / "policy-conflicts.jsonl"
REPORT_LOG = HERMES_HOME / "logs" / "maintenance"

ISO_NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- Scope analysis ---

VAGUE_SCOPE_KEYWORDS = [
    "always", "never", "whenever", "any", "all", "every", "everything",
    "anything", "nothing", "everywhere",
]

CONCRETE_SCOPE_KEYWORDS = [
    "if", "when", "while", "during", "after", "before",
    "except", "unless", "only",
    "in the case", "scoped to", "limited to",
    "exit code", "timeout", "error", "signal",
    "task type", "source", "context",
]


def analyze_scope(policy: dict) -> dict:
    """
    Analyze a policy's scope tightness.

    Returns dict with:
    - scope_rating: tight | broad | vague
    - has_scope_condition: bool
    - scope_text: extracted scope condition
    - recommendation: what to fix
    """
    rule = policy.get("rule", "")
    trigger = policy.get("trigger", "")
    combined = (rule + " " + trigger).lower()

    scope_condition = None

    # Look for scope conditions in the rule
    for kw in CONCRETE_SCOPE_KEYWORDS:
        if kw in combined:
            idx = combined.index(kw)
            scope_condition = combined[idx:idx+100]
            break

    # Check for vague terms without scope
    has_vague = any(kw in combined for kw in VAGUE_SCOPE_KEYWORDS)
    has_concrete = scope_condition is not None

    result = {
        "policy_id": policy.get("id", "unknown"),
        "scope_rating": "tight" if has_concrete else "broad" if has_vague else "unknown",
        "has_scope_condition": has_concrete,
        "scope_text": scope_condition,
    }

    if has_concrete:
        result["recommendation"] = "Scope is explicit — good."
    elif has_vague:
        result["recommendation"] = (
            f"Uses absolute terms ({', '.join(k for k in VAGUE_SCOPE_KEYWORDS if k in combined)}) "
            f"without scope condition. Add 'when X' or 'if Y' to prevent over-application."
        )
        result["scope_rating"] = "vague"
    else:
        result["recommendation"] = (
            "No explicit scope condition. "
            "Consider adding a scope condition if this policy is meant to be specific."
        )

    return result


# --- Contradiction detection ---

def extract_actions(rule: str) -> set:
    """Extract action verbs and their negation status from a rule."""
    rule_lower = rule.lower()
    actions = set()

    # DO actions
    do_patterns = [
        r"(?:^|\s)(use|run|call|set|dispatch|apply|write|create|add|enable)\s+(\w+)",
        r"(?:always|must|should)\s+(use|run|call|set|dispatch|apply|write|create|add|enable)\s+(\w+)",
    ]
    for pat in do_patterns:
        for match in re.finditer(pat, rule_lower):
            actions.add(("DO", f"{match.group(1)} {match.group(2)}"))

    # DON'T actions
    dont_patterns = [
        r"(?:^|\s)(don't|do not|never|avoid|stop|skip|donot)\s+(\w+(?:\s+\w+)?)",
        r"(?:must not|should not)\s+(use|run|call|set|dispatch|apply|write|create)\s+(\w+)",
    ]
    for pat in dont_patterns:
        for match in re.finditer(pat, rule_lower):
            g2 = match.group(2) if len(match.groups()) >= 2 else ""
            g3 = match.group(3) if len(match.groups()) >= 3 else ""
            actions.add(("DON'T", f"{g2} {g3}".strip()))

    return actions


def detect_contradictions(policies: List[dict]) -> List[dict]:
    """
    Find pairs of policies that contradict each other.

    A contradiction is: one policy says DO X, another says DON'T DO X
    for overlapping conditions.
    """
    contradictions = []
    seen_pairs = set()

    for i, p1 in enumerate(policies):
        actions1 = extract_actions(p1.get("rule", ""))
        for j, p2 in enumerate(policies):
            if i >= j:
                continue
            actions2 = extract_actions(p2.get("rule", ""))
            pair_key = (p1.get("id"), p2.get("id"))

            if pair_key in seen_pairs:
                continue

            # Check for DO vs DON'T on same action
            for do_verb, do_action in [(a[1], a[1]) for a in actions1 if a[0] == "DO"]:
                for dont_verb, dont_action in [(a[1], a[1]) for a in actions2 if a[0] == "DON'T"]:
                    # Check if they refer to the same action
                    do_words = set(do_action.split())
                    dont_words = set(dont_action.split())
                    if do_words & dont_words:  # share keywords
                        contradiction = {
                            "type": "direct_contradiction",
                            "policy_a": p1.get("id"),
                            "policy_b": p2.get("id"),
                            "a_says": f"DO: {do_action}",
                            "b_says": f"DON'T: {dont_action}",
                            "a_rule": p1.get("rule", "")[:100],
                            "b_rule": p2.get("rule", "")[:100],
                            "severity": "high",
                        }

                        # Scope analysis — check if scope resolves this
                        scope1 = analyze_scope(p1)
                        scope2 = analyze_scope(p2)

                        if scope1["scope_rating"] == "tight" and scope2["scope_rating"] == "vague":
                            contradiction["resolution"] = f"{p1.get('id')} wins (specific over general)"
                            contradiction["can_auto_resolve"] = True
                        elif scope2["scope_rating"] == "tight" and scope1["scope_rating"] == "vague":
                            contradiction["resolution"] = f"{p2.get('id')} wins (specific over general)"
                            contradiction["can_auto_resolve"] = True
                        else:
                            contradiction["resolution"] = "NEEDS_HUMAN — both have similar scope, unclear precedence"
                            contradiction["can_auto_resolve"] = False

                        contradictions.append(contradiction)
                        seen_pairs.add(pair_key)

    return contradictions


# --- Precedence resolution ---

def resolve_conflicts(policies: List[dict], contradictions: List[dict]) -> List[dict]:
    """
    Apply precedence rules to contradictions.

    Rules:
    1. Specific over general (default) — if one has tight scope, the other broad/vague
    2. Explicit precedence — flagged policies override by configured priority
    3. Both same scope → escalate to strategist

    Returns list of resolution records.
    """
    resolutions = []
    active_conflicts = [c for c in contradictions if not c.get("can_auto_resolve", False)]

    for c in contradictions:
        if c.get("can_auto_resolve", False):
            resolutions.append({
                "policy_a": c["policy_a"],
                "policy_b": c["policy_b"],
                "resolution": c["resolution"],
                "method": "specific_over_general",
                "applied_at": ISO_NOW,
                "audit_trail": f"Auto-resolved: {c['resolution']}",
            })
        else:
            # Cannot auto-resolve — flag for escalation
            resolutions.append({
                "policy_a": c["policy_a"],
                "policy_b": c["policy_b"],
                "resolution": c["resolution"],
                "method": "escalated",
                "applied_at": ISO_NOW,
                "audit_trail": f"Cannot auto-resolve. Both policies: {c['a_rule'][:60]} vs {c['b_rule'][:60]}",
            })

    return resolutions


# --- Conflict flagging in policy store ---

def flag_policy_conflicts(contradictions: List[dict], all_policies: List[dict]):
    """
    Mark conflicting policies with conflict metadata.
    Updates the policy JSON files with a _conflicts field.
    """
    for c in contradictions:
        policy_a_id = c["policy_a"]
        policy_b_id = c["policy_b"]

        for p in all_policies:
            if p.get("id") in (policy_a_id, policy_b_id):
                conflicts = p.get("_conflicts", [])
                new_conflict = {
                    "with": policy_b_id if p.get("id") == policy_a_id else policy_a_id,
                    "severity": c.get("severity", "unknown"),
                    "resolution": c.get("resolution", "unresolved"),
                    "can_auto_resolve": c.get("can_auto_resolve", False),
                }
                if new_conflict not in conflicts:
                    conflicts.append(new_conflict)
                p["_conflicts"] = conflicts

                # Write back to file
                policy_path = POLICY_DIR / f"{p['id']}.json" if "." not in p.get("id", "") else POLICY_DIR / f"{p['id']}.json"
                # Find the actual file
                for fname in os.listdir(POLICY_DIR):
                    if fname.endswith(".json") and p.get("id", "") in fname:
                        with open(os.path.join(POLICY_DIR, fname)) as f:
                            existing = json.load(f)
                        existing["_conflicts"] = conflicts
                        with open(os.path.join(POLICY_DIR, fname), "w") as f:
                            json.dump(existing, f, indent=2)
                        break


# --- Logging ---

def log_conflicts(contradictions: List[dict], resolutions: List[dict]):
    """Log conflict detection to conflict log."""
    entry = {
        "timestamp": ISO_NOW,
        "contradictions_found": len(contradictions),
        "auto_resolved": sum(1 for c in contradictions if c.get("can_auto_resolve", False)),
        "escalated": sum(1 for c in contradictions if not c.get("can_auto_resolve", False)),
        "contradictions": contradictions,
        "resolutions": resolutions,
    }
    os.makedirs(CONFLICTS_LOG.parent, exist_ok=True)
    with open(CONFLICTS_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


# --- Main ---

def run_conflict_resolution() -> dict:
    """Run the complete F3 conflict resolution pipeline."""
    # Load all policies
    policies = []
    for fname in sorted(os.listdir(POLICY_DIR)):
        if fname.endswith(".json"):
            try:
                with open(os.path.join(POLICY_DIR, fname)) as f:
                    policies.append(json.load(f))
            except (json.JSONDecodeError, IOError):
                continue

    # Phase 1: Scope analysis
    scope_results = [analyze_scope(p) for p in policies]
    vague_scope = [s for s in scope_results if s["scope_rating"] == "vague"]
    tight_scope = [s for s in scope_results if s["scope_rating"] == "tight"]

    # Phase 2: Contradiction detection
    contradictions = detect_contradictions(policies)

    # Phase 3: Resolution
    resolutions = resolve_conflicts(policies, contradictions)

    # Phase 4: Flag conflicts in policy files
    flag_policy_conflicts(contradictions, policies)

    # Log
    log_conflicts(contradictions, resolutions)

    return {
        "policies_analyzed": len(policies),
        "vague_scope": len(vague_scope),
        "tight_scope": len(tight_scope),
        "contradictions_found": len(contradictions),
        "auto_resolved": sum(1 for r in resolutions if r["method"] == "specific_over_general"),
        "escalated": sum(1 for r in resolutions if r["method"] == "escalated"),
        "vague_policies": [s["policy_id"] for s in vague_scope],
        "contradictions": contradictions,
        "resolutions": resolutions,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="F3 Conflict Resolution Engine")
    parser.add_argument("--run", action="store_true", help="Run full conflict resolution")
    parser.add_argument("--check", help="Check a specific policy for scope issues")
    parser.add_argument("--report", action="store_true", help="Generate conflict report")

    args = parser.parse_args()

    if args.run:
        result = run_conflict_resolution()
        print(f"=== F3 Conflict Resolution ===")
        print(f"  Policies analyzed: {result['policies_analyzed']}")
        print(f"  Vague scope: {result['vague_scope']}")
        print(f"  Tight scope: {result['tight_scope']}")
        print(f"  Contradictions: {result['contradictions_found']}")
        print(f"  Auto-resolved: {result['auto_resolved']}")
        print(f"  Escalated: {result['escalated']}")

        if result["vague_policies"]:
            print(f"\n  ⚠️ Vague scope policies:")
            for pid in result["vague_policies"]:
                print(f"     {pid}")

        if result["contradictions"]:
            print(f"\n  🔥 Contradictions:")
            for c in result["contradictions"]:
                status = "✅ auto" if c.get("can_auto_resolve") else "⚠️ escalated"
                print(f"     {status}: {c['policy_a']} vs {c['policy_b']}")
                print(f"       {c['resolution']}")

        if result["escalated"] > 0:
            print(f"\n  ❗ {result['escalated']} conflict(s) escalated — need review.")

        return 0

    if args.report:
        # Write report
        result = run_conflict_resolution()
        report_path = REPORT_LOG / f"conflict-report-{datetime.now().strftime('%Y-%m-%d')}.md"
        os.makedirs(REPORT_LOG, exist_ok=True)

        report_lines = [
            f"# Conflict Resolution Report",
            f"Generated: {ISO_NOW}",
            f"",
            f"## Summary",
            f"- Policies analyzed: {result['policies_analyzed']}",
            f"- Vague scope: {result['vague_scope']}",
            f"- Tight scope: {result['tight_scope']}",
            f"- Contradictions: {result['contradictions_found']}",
            f"- Auto-resolved: {result['auto_resolved']}",
            f"- Escalated: {result['escalated']}",
        ]

        if result.get("contradictions"):
            report_lines.append(f"\n## Contradictions")
            for c in result["contradictions"]:
                report_lines.append(f"### {c['policy_a']} vs {c['policy_b']}")
                report_lines.append(f"- Type: {c['type']}")
                report_lines.append(f"- Severity: {c['severity']}")
                report_lines.append(f"- {c['a_says']} (from {c['policy_a']})")
                report_lines.append(f"- {c['b_says']} (from {c['policy_b']})")
                report_lines.append(f"- Resolution: {c['resolution']}")
                report_lines.append("")

        with open(report_path, "w") as f:
            f.write("\n".join(report_lines))

        print(f"Report saved to {report_path}")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    main()
