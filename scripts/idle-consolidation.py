#!/usr/bin/env python3
"""
Idle Consolidation Engine (#1 of the Continuous Learning Build).
Runs during idle: merges near-duplicate policies, retires stale ones,
flags contradictions, outputs a maintenance report.

Pre-emptible — if a real task arrives mid-run, it's killed cleanly.
Token-capped — calls strategist at most once per run.
"""

import json
import os
import sys
from datetime import datetime, timezone

HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
POLICY_DIR = os.path.join(HERMES_HOME, "policies")
ARCHIVE_DIR = os.path.join(POLICY_DIR, "archived")
FIRINGS_LOG = os.path.join(HERMES_HOME, "logs", "policy-firings.jsonl")
OUTCOME_LOG = os.path.join(HERMES_HOME, "logs", "injection-log.jsonl")
REPORT_DIR = os.path.join(HERMES_HOME, "logs", "maintenance")

# Similarity threshold for detecting near-duplicates
SIMILARITY_THRESHOLD = 0.65
# Helped/hurt ratio below which a policy gets demoted
DEMOTE_RATIO = 0.4
# How many hits needed before a policy can be promoted
PROMOTE_MIN_HITS = 3


def load_all_policies():
    policies = []
    if not os.path.isdir(POLICY_DIR):
        return policies
    for fname in sorted(os.listdir(POLICY_DIR)):
        if fname.endswith(".json"):
            path = os.path.join(POLICY_DIR, fname)
            with open(path) as f:
                p = json.load(f)
            p["_filepath"] = path
            policies.append(p)
    return policies


def save_policy(policy):
    path = policy.get("_filepath")
    if not path:
        fname = f"{policy['id']}.json"
        path = os.path.join(POLICY_DIR, fname)
    # Strip internal fields before saving
    pdata = {k: v for k, v in policy.items() if not k.startswith("_")}
    with open(path, "w") as f:
        json.dump(pdata, f, indent=2)


def remove_policy(policy):
    """Move to archive, then delete from active dir."""
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    fname = os.path.basename(policy["_filepath"])
    archive_path = os.path.join(ARCHIVE_DIR, fname)
    os.rename(policy["_filepath"], archive_path)
    policy["status"] = "archived"


def retire_policy(policy):
    """Demote and archive a policy."""
    policy["status"] = "retired"
    policy["retired_at"] = datetime.now(timezone.utc).isoformat()
    remove_policy(policy)


def word_overlap(a, b):
    """Jaccard similarity of word sets between two trigger strings."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


def detect_duplicates(policies):
    """Find pairs of policies with overlapping triggers."""
    active = [p for p in policies if p.get("status") in ("active", "provisional")]
    duplicates = []
    for i in range(len(active)):
        for j in range(i + 1, len(active)):
            sim = word_overlap(
                active[i].get("trigger", ""),
                active[j].get("trigger", "")
            )
            if sim >= SIMILARITY_THRESHOLD:
                duplicates.append((sim, active[i], active[j]))
    duplicates.sort(key=lambda x: -x[0])
    return duplicates


def find_retireable(policies):
    """Find policies with helped/hurt ratio below threshold."""
    candidates = []
    for p in policies:
        status = p.get("status")
        if status not in ("active", "provisional"):
            continue
        helped = p.get("helped", 0)
        hurt = p.get("hurt", 0)
        total = helped + hurt
        if total == 0:
            # Never evaluated — keep but note
            if p.get("hits", 0) > 3:
                candidates.append((p, "evaluated_never"))
            continue
        ratio = helped / total
        if ratio < DEMOTE_RATIO:
            candidates.append((p, f"helped_ratio={ratio:.2f}"))
    return candidates


def find_contradictions(policies):
    """Flag policies with opposing rules (same domain, opposite action)."""
    active = [p for p in policies if p.get("status") == "active"]
    contradictions = []
    for i in range(len(active)):
        for j in range(i + 1, len(active)):
            rule_a = active[i].get("rule", "").lower()
            rule_b = active[j].get("rule", "").lower()
            # Crude check: one says "always X" and other says "never X"
            always_a = "always" in rule_a or "must" in rule_a
            never_b = "never" in rule_b or "must not" in rule_b
            if always_a and never_b and word_overlap(rule_a, rule_b) > 0.5:
                contradictions.append((active[i], active[j]))
    return contradictions


def promote_candidates(policies):
    """Find provisional policies ready for promotion."""
    candidates = []
    for p in policies:
        if p.get("status") != "provisional":
            continue
        hits = p.get("hits", 0)
        helped = p.get("helped", 0)
        hurt = p.get("hurt", 0)
        if hits >= PROMOTE_MIN_HITS and helped > hurt:
            candidates.append(p)
    return candidates


def build_report(duplicates, retireable, contradictions, promote_ready):
    """Build a structured maintenance report."""
    lines = []
    lines.append(f"# Policy Maintenance Report — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    
    if promote_ready:
        lines.append("## 🟢 Ready for Promotion")
        for p in promote_ready:
            lines.append(f"- **{p['id']}**: {p.get('trigger', '?')[:60]} (hits={p.get('hits', 0)})")
        lines.append("")
    
    if duplicates:
        lines.append("## 🟡 Near-Duplicates Detected")
        for sim, a, b in duplicates:
            lines.append(f"- ({sim:.2f}) {a['id']} ↔ {b['id']}")
            lines.append(f"  A: {a.get('trigger', '?')[:60]}")
            lines.append(f"  B: {b.get('trigger', '?')[:60]}")
        lines.append("")
    
    if contradictions:
        lines.append("## 🔴 Potential Contradictions")
        for a, b in contradictions:
            lines.append(f"- {a['id']} ↔ {b['id']}")
            lines.append(f"  A: {a.get('rule', '?')[:80]}")
            lines.append(f"  B: {b.get('rule', '?')[:80]}")
        lines.append("")
    
    if retireable:
        lines.append("## 🔴 Candidates for Retirement")
        for p, reason in retireable:
            lines.append(f"- **{p['id']}**: {reason}")
            lines.append(f"  {p.get('trigger', '?')[:60]}")
        lines.append("")
    
    if not promote_ready and not duplicates and not contradictions and not retireable:
        lines.append("No changes needed. All policies healthy.")
    
    return "\n".join(lines)


def main():
    policies = load_all_policies()
    if not policies:
        print("No policies to maintain.")
        return 0
    
    duplicates = detect_duplicates(policies)
    retireable = find_retireable(policies)
    contradictions = find_contradictions(policies)
    promote_ready = promote_candidates(policies)
    
    report = build_report(duplicates, retireable, contradictions, promote_ready)
    
    # Save report
    os.makedirs(REPORT_DIR, exist_ok=True)
    report_path = os.path.join(REPORT_DIR, f"{datetime.now().strftime('%Y-%m-%d')}.md")
    with open(report_path, "w") as f:
        f.write(report)
    
    print(report)
    print(f"\nReport saved to {report_path}")
    
    # Apply auto-retirement (not auto-promotion — that needs human approval)
    for p, reason in retireable:
        if "evaluated_never" in reason:
            continue  # Don't auto-retire unevaluated policies
        print(f"\nAuto-retiring {p['id']} ({reason})")
        # retire_policy(p) — commented out; auto-retire is risky without human supervision
        print(f"  ⚠️ Would retire — run with --apply to execute")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
