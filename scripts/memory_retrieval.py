#!/usr/bin/env python3
"""
Memory retrieval — Phase 3: embedding-based retrieval layer.

Delegates to retrieval.embedding_recall for:
- Embedding-based semantic recall (all-MiniLM-L6-v2 ONNX, 384-dim)
- Tag-filter keyword first-pass (supplement)
- Self-query routing (memory vs policy vs both)
- Policy-level slicing (inject only policies relevant to task)

Build order (F1): This is the retrieval prerequisite that gates A and B.
"""

import json
import os
import sys
from datetime import datetime

# Add our retrieval module to path
HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
sys.path.insert(0, os.path.join(HERMES_HOME, "scripts"))

INJECTION_LOG = os.path.join(HERMES_HOME, "logs", "injection-log.jsonl")
_EMBED_WARNED = False  # log numpy/onnx ImportError once, not every tick

# INVARIANTS (always injected)
INVARIANTS = """## INVARIANTS (always injected)
1. Source-or-die: every factual claim cites retrievable source or is unverifiable
2. Kill-fast: cheapest decisive gate first
3. Hermes owns control loop; Claude consulted at decisions; Minimax for cheap execution
4. Never commit secrets to git or output
5. Never substitute fabricated output for real execution results"""


def build_payload(task_text: str) -> str:
    """Build filtered injection payload using the F1 retrieval layer."""
    try:
        from retrieval import tag_filter, embedding_recall
        idx = embedding_recall.get_index()
        payload_parts, log_entry = embedding_recall.build_injection_payload(
            task_text, index=idx
        )
    except ImportError as e:
        # Fallback: basic tag-only retrieval (log once — numpy/onnx missing is sticky)
        global _EMBED_WARNED
        if not _EMBED_WARNED:
            print(
                f"[memory_retrieval] Embedding layer unavailable ({e}); "
                f"using tag-only (silence further spam)",
                file=sys.stderr,
            )
            _EMBED_WARNED = True
        payload_parts, log_entry = _tag_only_fallback(task_text)

    # Log the injection
    _log_injection(log_entry)

    # Check and fire matching policies — this is the missing link.
    # Policies were loaded but never automatically checked against tasks.
    try:
        import policy_enforcer
        fired = policy_enforcer.check_and_fire_policies(task_text, context="injection")
        if fired:
            log_entry["policies_fired"] = fired
    except Exception:
        pass

    return payload_parts


def _tag_only_fallback(task_text: str) -> tuple:
    """Fallback when embedding layer can't load — uses tag-filter only.

    Was: dumped ALL policies regardless of task relevance, and memory threshold
    was 0.3 (too high for untagged entries). Now: filters policies by keyword
    overlap too, and lowers the memory bar so at least some entries surface.
    """
    from retrieval import tag_filter

    entries = _load_memory_entries()
    user_profile = _load_user_profile()
    active_policies = _load_active_policies()

    # Lower threshold from 0.3 -> 0.1 so untagged entries with keyword overlap
    # still surface. The old 0.3 was tuned for tagged entries which don't exist.
    candidates = tag_filter.filter_entries(entries, task_text, threshold=0.1)
    retrieved = [e for _, e in candidates]

    # Filter policies by task relevance. Was dumping all 7 regardless of task —
    # a policy about "killing processes" is noise when the task is "check moat health."
    task_lower = task_text.lower()
    relevant_policies = []
    for p in active_policies:
        trigger = str(p.get("trigger", "") or "").lower()
        rule = str(p.get("rule", "") or "").lower()
        pid = str(p.get("id", "") or "")
        # Score: count keyword overlap between task and policy trigger/rule
        task_words = set(w for w in task_lower.split() if len(w) > 2)
        policy_words = set(w for w in (trigger + " " + rule).split() if len(w) > 2)
        if task_words:
            overlap = len(task_words & policy_words) / len(task_words)
        else:
            overlap = 0
        # Also match if the task contains the policy's domain keywords
        if overlap >= 0.15 or any(kw in task_lower for kw in policy_words if len(kw) > 4):
            relevant_policies.append(p)

    log_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "task": task_text[:200],
        "mode": "tag-only-fallback",
        "total_entries": len(entries),
        "retrieved_count": len(retrieved),
        "active_policies_count": len(active_policies),
        "relevant_policies_count": len(relevant_policies),
    }

    parts = []
    parts.append(INVARIANTS)

    if retrieved:
        parts.append(f"\n[RETRIEVED MEMORY — {len(retrieved)} entries]")
        for entry in retrieved:
            tags = tag_filter.extract_tags(entry)
            tag_str = " ".join(f"{k}:{v}" for k, v in tags.items()) if tags else "untagged"
            parts.append(f"  [{tag_str}] {entry[:400]}")
    else:
        parts.append(f"\n[RETRIEVED MEMORY — 0 entries matched]")

    if relevant_policies:
        parts.append(f"\n[ACTIVE POLICIES — {len(relevant_policies)} of {len(active_policies)} relevant]")
        for p in relevant_policies:
            parts.append(f"  ⚠️ {p['id']}: {p['trigger'][:100]}")
            parts.append(f"     → {p['rule'][:200]}")
    elif active_policies:
        parts.append(f"\n[ACTIVE POLICIES — 0 of {len(active_policies)} relevant to this task]")

    if user_profile:
        parts.append(f"\n[USER PROFILE]")
        parts.append(user_profile[:500])

    return "\n".join(parts), log_entry


def _load_memory_entries() -> list:
    """Load MEMORY.md and parse tagged entries."""
    memory_file = os.path.join(HERMES_HOME, "memories", "MEMORY.md")
    if not os.path.exists(memory_file):
        return []

    with open(memory_file) as f:
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


def _load_user_profile() -> str:
    user_file = os.path.join(HERMES_HOME, "memories", "USER.md")
    if os.path.exists(user_file):
        with open(user_file) as f:
            return f.read()
    return ""


def _load_active_policies() -> list:
    policy_dir = os.path.join(HERMES_HOME, "policies")
    if not os.path.isdir(policy_dir):
        return []
    policies = []
    for fname in sorted(os.listdir(policy_dir)):
        if fname.endswith(".json"):
            try:
                with open(os.path.join(policy_dir, fname)) as f:
                    p = json.load(f)
                if p.get("status") in ("active", "provisional"):
                    policies.append(p)
            except (json.JSONDecodeError, IOError):
                continue
    return policies


def _log_injection(log_entry: dict):
    os.makedirs(os.path.dirname(INJECTION_LOG), exist_ok=True)
    with open(INJECTION_LOG, "a") as f:
        f.write(json.dumps(log_entry) + "\n")


def main():
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else sys.stdin.read().strip()
    if not task:
        print("Usage: memory_retrieval.py <task description>")
        print("Returns structured payload for strategist call injection.")
        sys.exit(1)

    payload = build_payload(task)
    print(payload)


if __name__ == "__main__":
    main()
