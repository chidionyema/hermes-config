#!/usr/bin/env python3
"""
Memory retrieval Phase 2 — self-query routing with policy injection.

Phase 1 was the design doc. Phase 2 is the working implementation:
- Tag-based routing (project:domain:type)
- Confidence scoring threshold (>= 0.5 accepted)
- Policy injection: active policies always included when relevant
- Injection logging for diagnosability

Called by the operating model before every strategist dispatch.
"""

import json
import os
import re
from datetime import datetime

HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
MEMORY_FILE = os.path.join(HERMES_HOME, "memories", "MEMORY.md")
USER_FILE = os.path.join(HERMES_HOME, "memories", "USER.md")
POLICY_DIR = os.path.join(HERMES_HOME, "policies")
INJECTION_LOG = os.path.join(HERMES_HOME, "logs", "injection-log.jsonl")

# Tag schemas for routing
PROJECT_KEYWORDS = {
    "prospector": ["prospector", "store", ".net", "fulfil", "publish", "golden set", "bridge", "packs", "entitlements", "catalog", "provisional"],
    "signal-engine": ["signal engine", "trading", "signal", "portfolio", "risk", "execution", "reconciliation", "strategy", "validation"],
    "lux": ["lux", "pdd", "proof", "verify", "spec", "popdd", "type-level", "formal verification"],
    "hermes-config": ["hermes", "config", "otto", "gateway", "telegram", "cron", "policy", "skill", "memory", "audit", "backup", "backed up"],
}

DOMAIN_KEYWORDS = {
    "go-live": ["launch", "go-live", "p0", "blocker", "production", "deploy", "ship", "release", "prod"],
    "pdd": ["spec", "verify", "proof", "property test", "edge case", "contract", "invariant", "assertion"],
    "infra": ["config", "setup", "backup", "git", "github", "deploy", "ci", "cron", "service", "agent"],
    "trading": ["trade", "signal", "momentum", "btc", "usdt", "crypto", "fill", "order", "execution"],
}

TYPE_KEYWORDS = {
    "state": ["status", "health", "where", "how many", "progress", "check"],
    "decision": ["should", "decide", "option", "trade-off", "choose", "architect"],
    "lesson": ["mistake", "correct", "wrong", "fix", "never", "avoid", "bug", "error"],
    "constraint": ["must", "must not", "never", "always", "invariant", "rule", "requirement"],
    "preference": ["prefer", "like", "want", "style", "convention", "habit"],
}

INVARIANTS = """## INVARIANTS (always injected)
1. Source-or-die: every factual claim cites retrievable source or is unverifiable
2. Kill-fast: cheapest decisive gate first
3. Hermes owns control loop; Claude consulted at decisions; Minimax for cheap execution
4. Never commit secrets to git or output
5. Never substitute fabricated output for real execution results"""


def load_memory():
    """Load MEMORY.md and parse tagged entries."""
    if not os.path.exists(MEMORY_FILE):
        return []
    with open(MEMORY_FILE) as f:
        content = f.read()
    
    entries = []
    current = ""
    for line in content.split("\n"):
        if line.startswith("[tags:"):
            if current.strip():
                entries.append(current.strip())
            current = line
        else:
            current += "\n" + line
    if current.strip():
        entries.append(current.strip())
    
    return entries


def load_user_profile():
    """Load USER.md content."""
    if not os.path.exists(USER_FILE):
        return ""
    with open(USER_FILE) as f:
        return f.read()


def load_active_policies():
    """Load policies with status=active."""
    if not os.path.isdir(POLICY_DIR):
        return []
    policies = []
    for fname in sorted(os.listdir(POLICY_DIR)):
        if fname.endswith(".json"):
            try:
                with open(os.path.join(POLICY_DIR, fname)) as f:
                    p = json.load(f)
                if p.get("status") == "active":
                    policies.append(p)
            except (json.JSONDecodeError, IOError):
                continue
    return policies


def extract_tags(text):
    """Extract [tags: ...] from an entry."""
    m = re.search(r'\[tags:\s*(.*?)\]', text)
    if m:
        parts = m.group(1).split()
        tags = {}
        for part in parts:
            if ":" in part:
                k, v = part.split(":", 1)
                tags[k] = v
        return tags
    return {}


def score_entry(entry_text, task_text):
    """Score how relevant an entry is to the task. Returns 0.0-1.0."""
    tags = extract_tags(entry_text)
    task_lower = task_text.lower()
    entry_lower = entry_text.lower()
    
    score = 0.0
    match_count = 0
    
    # Tag matching
    if "project" in tags:
        keywords = {}
        for k, v_list in PROJECT_KEYWORDS.items():
            keywords.update({kw: k for kw in v_list})
        for kw, project in keywords.items():
            if kw in task_lower:
                if tags["project"].lower() == project:
                    score += 0.3
                    match_count += 1
    
    if "domain" in tags:
        for domain, keywords in DOMAIN_KEYWORDS.items():
            for kw in keywords:
                if kw in task_lower:
                    if tags.get("domain", "").lower() == domain:
                        score += 0.2
                        match_count += 1
    
    if "type" in tags:
        for etype, keywords in TYPE_KEYWORDS.items():
            for kw in keywords:
                if kw in task_lower:
                    if tags.get("type", "").lower() == etype:
                        score += 0.15
                        match_count += 1
    
    # Content match: shared words
    task_words = set(task_lower.split())
    entry_words = set(entry_lower.split())
    common = task_words & entry_words
    if len(task_words) > 0:
        score += 0.25 * (len(common) / len(task_words))
    
    if match_count > 0:
        score = min(score, 1.0)
    
    return score


def route(entries, task_text, threshold=0.5):
    """Route entries by relevance to task. Returns filtered, scored list."""
    candidates = []
    for entry in entries:
        score = score_entry(entry, task_text)
        if score >= threshold:
            candidates.append((score, entry))
    
    candidates.sort(key=lambda x: -x[0])
    return candidates


def build_payload(task_text):
    """
    Build the full injection payload for a strategist dispatch.
    Returns (payload_text, injection_log_entry).
    """
    entries = load_memory()
    user_profile = load_user_profile()
    active_policies = load_active_policies()
    
    # Route memory
    candidates = route(entries, task_text)
    retrieved = [e for _, e in candidates]
    
    # Build injection log
    log_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "task": task_text[:200],
        "total_entries": len(entries),
        "retrieved_count": len(retrieved),
        "retrieved_tags": [extract_tags(e) for e in retrieved],
        "active_policies_count": len(active_policies),
        "active_policy_triggers": [p.get("trigger", "?")[:60] for p in active_policies],
    }
    
    # Build payload
    parts = []
    
    parts.append("[INVARIANTS]")
    parts.append(INVARIANTS)
    
    parts.append(f"\n[RETRIEVED MEMORY — {len(retrieved)} entries]")
    for entry in retrieved:
        tags = extract_tags(entry)
        tag_str = " ".join(f"{k}:{v}" for k, v in tags.items()) if tags else "untagged"
        parts.append(f"  [{tag_str}] {entry[:400]}")
    
    for entry in entries:
        if entry not in retrieved:
            tags = extract_tags(entry)
            tag_str = " ".join(f"{k}:{v}" for k, v in tags.items()) if tags else "untagged"
            score = score_entry(entry, task_text)
            if 0.2 <= score < 0.5:
                parts.append(f"  [{tag_str}] (low relevance: {score:.2f}) {entry[:200]}")
    
    if active_policies:
        parts.append(f"\n[ACTIVE POLICIES — {len(active_policies)} active]")
        for p in active_policies:
            parts.append(f"  ⚠️ {p['id']}: {p['trigger'][:100]}")
            parts.append(f"     → {p['rule'][:200]}")
    
    if user_profile:
        parts.append(f"\n[USER PROFILE — {len(user_profile)} chars]")
        parts.append(user_profile[:500])
    
    payload = "\n".join(parts)
    
    return payload, log_entry


def log_injection(log_entry):
    """Write injection log entry."""
    os.makedirs(os.path.dirname(INJECTION_LOG), exist_ok=True)
    with open(INJECTION_LOG, "a") as f:
        f.write(json.dumps(log_entry) + "\n")


def main():
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else sys.stdin.read().strip()
    if not task:
        print("Usage: memory_retrieval.py <task description>")
        print("Returns structured payload for strategist call injection.")
        sys.exit(1)
    
    payload, log_entry = build_payload(task)
    log_injection(log_entry)
    
    print(payload)
    
    # Metrics to stderr
    print(f"\n[Injection: {log_entry['retrieved_count']} entries, {log_entry['active_policies_count']} policies]", file=sys.stderr)


if __name__ == "__main__":
    import sys
    main()
