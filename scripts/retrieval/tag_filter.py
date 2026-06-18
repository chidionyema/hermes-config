"""
Tag-filter — keyword-based first-pass retrieval.

Fast AND-level keyword matching against project/domain/type schemas.
Returns (score, entry) for entries matching >= threshold (default 0.3).

This is the first pass: cheap, deterministic, always runs.
"""

import re
from typing import List, Tuple, Dict

# Tag schemas for routing
PROJECT_KEYWORDS: Dict[str, List[str]] = {
    "prospector": ["prospector", "store", ".net", "fulfil", "publish", "golden set",
                    "bridge", "packs", "entitlements", "catalog", "provisional"],
    "signal-engine": ["signal engine", "trading", "signal", "portfolio", "risk",
                       "execution", "reconciliation", "strategy", "validation", "momentum"],
    "lux": ["lux", "pdd", "proof", "verify", "spec", "popdd", "type-level",
            "formal verification", "property test", "edge case", "contract"],
    "hermes-config": ["hermes", "config", "otto", "gateway", "telegram", "cron",
                       "policy", "skill", "memory", "audit", "backup", "backed up",
                       "gate", "dispatch", "improver"],
}

DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    "go-live": ["launch", "go-live", "p0", "blocker", "production", "deploy",
                 "ship", "release", "prod"],
    "pdd": ["spec", "verify", "proof", "property test", "edge case", "contract",
            "invariant", "assertion", "property", "correctness"],
    "infra": ["config", "setup", "backup", "git", "github", "deploy", "ci",
               "cron", "service", "agent", "dispatch", "ssh"],
    "trading": ["trade", "signal", "momentum", "btc", "usdt", "crypto", "fill",
                 "order", "execution", "portfolio", "risk"],
}

TYPE_KEYWORDS: Dict[str, List[str]] = {
    "state": ["status", "health", "where", "how many", "progress", "check",
              "current", "state"],
    "decision": ["should", "decide", "option", "trade-off", "choose", "architect",
                 "proposal", "recommend", "compare"],
    "lesson": ["mistake", "correct", "wrong", "fix", "never", "avoid", "bug",
               "error", "failure", "regression"],
    "constraint": ["must", "must not", "never", "always", "invariant", "rule",
                   "requirement", "mandatory", "blocker"],
    "preference": ["prefer", "like", "want", "style", "convention", "habit",
                   "taste", "way"],
}


def extract_tags(text: str) -> Dict[str, str]:
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


def score_entry(entry_text: str, task_text: str) -> float:
    """
    Score how relevant an entry is to the task. Returns 0.0-1.0.

    Scoring:
    - Project match: +0.3 per matching keyword
    - Domain match: +0.2 per keyword
    - Type match: +0.15 per keyword
    - Content overlap: +0.25 * (shared_words / task_words)
    """
    tags = extract_tags(entry_text)
    task_lower = task_text.lower()
    entry_lower = entry_text.lower()

    score = 0.0
    match_count = 0

    # Project tag matching
    if "project" in tags:
        # Build reverse keyword map
        keywords = {}
        for proj, kw_list in PROJECT_KEYWORDS.items():
            for kw in kw_list:
                keywords[kw] = proj
        for kw, project in keywords.items():
            if kw in task_lower and tags["project"].lower() == project:
                score += 0.3
                match_count += 1

    # Domain tag matching
    if "domain" in tags:
        for domain, keywords in DOMAIN_KEYWORDS.items():
            for kw in keywords:
                if kw in task_lower and tags.get("domain", "").lower() == domain:
                    score += 0.2
                    match_count += 1

    # Type tag matching
    if "type" in tags:
        for etype, keywords in TYPE_KEYWORDS.items():
            for kw in keywords:
                if kw in task_lower and tags.get("type", "").lower() == etype:
                    score += 0.15
                    match_count += 1

    # Content match: shared word ratio
    task_words = set(w for w in task_lower.split() if len(w) > 2)
    entry_words = set(w for w in entry_lower.split() if len(w) > 2)
    if task_words:
        common = task_words & entry_words
        score += 0.25 * (len(common) / len(task_words))

    if match_count > 0:
        score = min(score, 1.0)

    return score


def filter_entries(entries: list, task_text: str,
                   threshold: float = 0.3) -> List[Tuple[float, str]]:
    """
    Filter entries by keyword relevance.
    Returns sorted list of (score, entry) tuples.
    """
    candidates = []
    for entry in entries:
        score = score_entry(entry, task_text)
        if score >= threshold:
            candidates.append((score, entry))

    candidates.sort(key=lambda x: -x[0])
    return candidates


def get_low_relevance(entries: list, task_text: str,
                      min_score: float = 0.1,
                      max_score: float = 0.3) -> List[Tuple[float, str]]:
    """Get entries that partially matched but didn't pass the threshold."""
    candidates = []
    for entry in entries:
        score = score_entry(entry, task_text)
        if min_score <= score < max_score:
            candidates.append((score, entry))
    candidates.sort(key=lambda x: -x[0])
    return candidates
