"""
Otto Memory Retrieval Layer — Phase 1 implementation.
Tag-filtered retrieval, self-query routing, injection logging.

Usage:
    from memory_retrieval import build_strategist_payload
    payload, log_entry = build_strategist_payload(task_description, memory_entries, task_state)

Requirements: Python 3.11+, standard library only.
"""

import json
import re
import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# --- Configuration ---

INJECTION_LOG_PATH = Path.home() / ".hermes" / "logs" / "injection-log.jsonl"
MAX_RETRIEVED_SLICE = 6  # Max entries in retrieved slice
CONFIDENCE_THRESHOLD = 0.2
INVARIANTS_MARKER = "INVARIANTS"

# --- Tag schema vocabulary ---

PROJECTS = {
    "prospector": ["prospector", "idea", "vetting", "fulfilment", "payment", "business", "paddle", "store"],
    "lux": ["lux", "pdd", "popdd", "spec", "verify", "proof", "guard", "cli", "typescript", "formal"],
    "signal-engine": ["signal", "engine", "trading", "crypto", "btc", "usdt", "momentum", "portfolio", "risk"],
    "hermes-config": ["hermes", "profile", "skill", "cron", "memory", "config", "otto"],
    "general": [],  # wildcard — matches everything
}

DOMAINS = {
    "trading": ["market", "trade", "signal", "crypto", "momentum", "btc", "usdt", "execution", "portfolio"],
    "pdd": ["spec", "pdd", "proof", "verify", "receipt", "guard", "formal", "invariant"],
    "go-live": ["go-live", "production", "deploy", "payment", "legal", "entitle", "ci", "gate", "launch"],
    "infra": ["config", "tool", "env", "ci", "cd", "plumbing", "pipeline", "setup", "dependency"],
}

TYPES = {
    "state": ["state", "status", "current", "blocker", "progress", "test", "count"],
    "decision": ["decide", "decision", "architecture", "choose", "rationale"],
    "preference": ["prefer", "preference", "like", "style", "convention"],
    "environment": ["path", "version", "env", "tool", "dependency", "repo"],
    "constraint": ["constraint", "rule", "invariant", "must", "never", "always", "blocker"],
    "lesson": ["lesson", "learn", "gotcha", "history", "pitfall"],
}

# --- Data types ---

@dataclass
class MemoryEntry:
    id: int
    text: str
    tags: dict = field(default_factory=dict)  # parsed from [tags: ...] in text

    @classmethod
    def from_text(cls, text: str, entry_id: int) -> "MemoryEntry":
        tags = parse_tags(text)
        return cls(id=entry_id, text=text, tags=tags)

def parse_tags(text: str) -> dict:
    """Extract tags from memory entry text. Format: [tags: project:xxx domain:yyy type:zzz]"""
    match = re.search(r'\[tags:\s*(.*?)\]', text)
    if not match:
        return {}
    
    parts = match.group(1).split()
    tags = {}
    for part in parts:
        if ':' in part:
            key, value = part.split(':', 1)
            tags[key] = value
    return tags

# --- Self-query routing ---

def self_query_tags(task_description: str) -> list[dict]:
    """
    Rule-based tag classification from task description.
    Returns list of {project, domain, type, confidence} dicts.
    """
    text_lower = task_description.lower()
    candidates = []

    def score_category(vocab: dict[str, list[str]], category_name: str) -> list[dict]:
        results = []
        for tag, keywords in vocab.items():
            if not keywords:
                continue
            matched = sum(1 for kw in keywords if kw in text_lower)
            # Score: matched/total vocab size for that tag, but floor 0.1 for any match
            if matched > 0:
                conf = max(0.1, matched / len(keywords))
                results.append({category_name: tag, "confidence": conf})
        return results

    project_scores = score_category(PROJECTS, "project")
    domain_scores = score_category(DOMAINS, "domain")
    type_scores = score_category(TYPES, "type")

    # Always include the general wildcard at confidence 0.4
    if not any(s.get("project") == "general" for s in project_scores):
        project_scores.append({"project": "general", "confidence": 0.4})
    if not any(s.get("domain") == "general" for s in domain_scores):
        domain_scores.append({"domain": "general", "confidence": 0.4})
    if not any(s.get("type") == "general" for s in type_scores):
        type_scores.append({"type": "general", "confidence": 0.4})

    # Build cartesian product of candidates
    if not project_scores:
        project_scores = [{"project": "general", "confidence": 0.5}]
    if not domain_scores:
        domain_scores = [{"domain": "infra", "confidence": 0.5}]
    if not type_scores:
        type_scores = [{"type": "state", "confidence": 0.5}]

    for ps in project_scores:
        for ds in domain_scores:
            for ts in type_scores:
                avg_conf = (ps["confidence"] + ds["confidence"] + ts["confidence"]) / 3
                candidates.append({
                    "project": ps["project"],
                    "domain": ds["domain"],
                    "type": ts["type"],
                    "confidence": round(avg_conf, 3),
                })

    # Sort by confidence descending, deduplicate by keeping highest
    candidates.sort(key=lambda c: c["confidence"], reverse=True)
    seen = set()
    unique = []
    for c in candidates:
        key = (c["project"], c["domain"], c["type"])
        if key not in seen:
            seen.add(key)
            unique.append(c)

    return unique

# --- Memory filtering ---

def filter_memories(
    entries: list[MemoryEntry],
    accepted_tags: list[dict],
    invariants: Optional[MemoryEntry] = None,
    max_slice: int = MAX_RETRIEVED_SLICE,
) -> tuple[list[MemoryEntry], list[MemoryEntry]]:
    """
    Returns (invariants_list, retrieved_slice).
    
    Filtering: entry tags match if any accepted tag matches on all three axes
    (project, domain, type). 'general' is a wildcard that matches anything.
    """
    retrieved = []
    
    for entry in entries:
        # Skip INVARIANTS — handled separately
        if entry.tags.get("type") == "constraint" or INVARIANTS_MARKER in entry.text:
            continue
            
        for candidate in accepted_tags:
            proj_match = (entry.tags.get("project") == candidate.get("project") 
                         or candidate.get("project") == "general")
            domain_match = (entry.tags.get("domain") == candidate.get("domain")
                          or candidate.get("domain") == "general")
            type_match = (entry.tags.get("type") == candidate.get("type")
                        or candidate.get("type") == "general")
            
            if proj_match and domain_match and type_match:
                retrieved.append(entry)
                break

    # Deduplicate by ID
    seen_ids = set()
    deduped = []
    for e in retrieved:
        if e.id not in seen_ids:
            seen_ids.add(e.id)
            deduped.append(e)

    return deduped[:max_slice]

# --- Injection logging ---

def log_injection(log_entry: dict) -> None:
    """Append a JSON line to the injection log."""
    INJECTION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(INJECTION_LOG_PATH, "a") as f:
        f.write(json.dumps(log_entry, default=str) + "\n")

# --- Payload builder ---

def build_strategist_payload(
    task_description: str,
    memory_entries: list[str],
    task_state: Optional[dict] = None,
    target_model: str = "claude-sonnet",
) -> tuple[str, dict]:
    """
    Build the injected payload for a strategist call.
    
    Returns:
        payload_string: The formatted string to inject
        log_entry: Dict to write to injection log
    """
    # Parse entries
    entries = [MemoryEntry.from_text(t, i) for i, t in enumerate(memory_entries)]
    
    # Find invariants
    invariants_entry = None
    for e in entries:
        if e.tags.get("type") == "constraint" or INVARIANTS_MARKER in e.text:
            invariants_entry = e
            break
    
    non_invariant = [e for e in entries if e.id != (invariants_entry.id if invariants_entry else -1)]
    
    # Self-query
    candidates = self_query_tags(task_description)
    accepted = [c for c in candidates if c["confidence"] >= CONFIDENCE_THRESHOLD]
    
    fallback_used = False
    if not accepted:
        accepted = [{"project": "general", "domain": "infra", "type": "state", "confidence": 0.5}]
        fallback_used = True
    
    # Filter
    retrieved_slice = filter_memories(non_invariant, accepted, invariants_entry)
    
    # Build payload
    parts = []
    
    if invariants_entry:
        parts.append("[INVARIANTS]")
        parts.append(invariants_entry.text)
        parts.append("")
    
    if retrieved_slice:
        parts.append("[RETRIEVED SLICE]")
        for e in retrieved_slice:
            parts.append(e.text)
            parts.append("")
    
    if task_state:
        parts.append("[TASK STATE]")
        if "goal" in task_state:
            parts.append(f"Current goal: {task_state['goal']}")
        if "done" in task_state:
            parts.append(f"Done so far: {task_state['done']}")
        if "results" in task_state:
            parts.append(f"Last results: {task_state['results']}")
        if "blockers" in task_state:
            parts.append(f"Blockers: {task_state['blockers']}")
    
    payload = "\n".join(parts)
    
    # Build log entry
    call_id = f"strat-{time.strftime('%Y%m%d-%H%M%S')}-{hashlib.md5(task_description.encode()).hexdigest()[:8]}"
    
    total_chars = sum(len(e.text) for e in retrieved_slice)
    if invariants_entry:
        total_chars += len(invariants_entry.text)
    if task_state:
        total_chars += sum(len(v) for v in task_state.values()) if isinstance(task_state, dict) else 0
    
    log_entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "call_id": call_id,
        "target_model": target_model,
        "task_summary": task_description[:80],
        "candidate_tags": candidates[:5],
        "accepted_tags": accepted,
        "invariants_injected": invariants_entry is not None,
        "retrieved_slice_entries": len(retrieved_slice),
        "retrieved_entry_ids": [e.id for e in retrieved_slice],
        "retrieved_total_chars": total_chars,
        "slice_cap_applied": len(retrieved_slice) >= MAX_RETRIEVED_SLICE,
        "embedding_recall_used": False,
        "task_state_injected": task_state is not None,
        "fallback_used": fallback_used,
    }
    
    log_injection(log_entry)
    
    return payload, log_entry


# --- CLI for testing ---

def cli():
    """Run a self-query test from the command line."""
    import sys
    if len(sys.argv) < 2:
        print("Usage: python memory_retrieval.py <task description>")
        sys.exit(1)
    
    task = " ".join(sys.argv[1:])
    print(f"Task: {task}\n")
    
    candidates = self_query_tags(task)
    accepted = [c for c in candidates if c["confidence"] >= CONFIDENCE_THRESHOLD]
    
    print("Candidates (top 10):")
    for c in candidates[:10]:
        marker = "✓" if c["confidence"] >= CONFIDENCE_THRESHOLD else " "
        print(f"  {marker} project:{c['project']} domain:{c['domain']} type:{c['type']} (conf={c['confidence']})")
    
    if not accepted:
        print("\n→ Fallback: general/infra/state (confidence 0.5)")
    else:
        print(f"\n→ Accepted: {len(accepted)} tags")


if __name__ == "__main__":
    cli()
