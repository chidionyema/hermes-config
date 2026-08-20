"""One capability vocabulary, shared by the half that finds gaps and the half that records outcomes.

WHY THIS FILE EXISTS. Until 2026-08-20 the self-improvement loop had two halves that each worked
and never once agreed on a key.

  * `gap-finding.py` classified failures into capability domains with an inline keyword ladder:
    terminal, testing, decision-making, file_io, api_usage, task-management, process-management,
    self-improvement, deployment, git, automation, delegation, memory.
  * `outcome_tracker.py` recorded task outcomes tagged with whatever the caller passed, and the
    caller passed nothing, so `coordinator.py` fell through to its default string "coordinator".

Measured 2026-08-19: 61 shadow policies covering the domains "automation" and "api_usage", and
259 recorded outcomes covering "coordinator" (243), "python" (14), "agent" (1) and "shell" (1).
The intersection is EMPTY. `GapCloser._assess_risk` asks "how many outcomes in domain X" and can
never get an answer above zero, so no gap is graded LOW, nothing is auto-promoted, and
`evaluate_shadow` waits forever. 244 hourly cycles, 1723 gaps found, 0 closed.

Neither vocabulary was wrong. Nothing compared them. Both halves now import `classify` from here,
so the two can only ever drift together.

A note on what this does NOT do: the 259 rows already in `state/outcomes.db` keep their old tags.
Evidence accumulates from now on; it is not back-filled, because re-tagging a recorded outcome
from its task id would be a guess and the whole point of the loop is that it rules on evidence.
"""
from __future__ import annotations

from collections import Counter

# The capability domains this agent reasons about. Lifted verbatim from the ladder that was
# inline in gap-finding.py:113 so the migration changes no classification.
CAPABILITY_DOMAINS: dict[str, tuple[str, ...]] = {
    "terminal":           ("terminal", "command", "shell", "build"),
    "testing":            ("test", "verify", "pytest", "test suite", "golden"),
    "decision-making":    ("ask", "permission", "question", "should i"),
    "file_io":            ("file", "read", "write", "patch", "search"),
    "api_usage":          ("api", "signature", "import", "function call"),
    "task-management":    ("background", "sync", "timeout", "wait"),
    "process-management": ("kill", "process", "pid", "stop"),
    "self-improvement":   ("reflect", "correct", "improve", "learn"),
    "deployment":         ("deploy", "launch", "go-live", "production"),
    "git":                ("git", "commit", "push", "branch"),
    "automation":         ("cron", "schedule", "automate", "timer"),
    "delegation":         ("delegate", "subagent", "parallel"),
    "memory":             ("memory", "remember", "forget", "store"),
}

# Where a task ran, not what capability it exercised. These are the strings the outcome writers
# used as defaults before this module existed; they are kept out of the capability vocabulary so
# a caller passing one is not mistaken for a classification.
EXECUTOR_TAGS = frozenset({"coordinator", "python", "agent", "shell", "unknown", ""})


def count_domains(text: str) -> Counter:
    """Every capability domain whose keywords appear in `text`. A failure can span several."""
    lowered = (text or "").lower()
    hits = Counter()
    for domain, keywords in CAPABILITY_DOMAINS.items():
        if any(word in lowered for word in keywords):
            hits[domain] += 1
    return hits


def classify(text: str, default: str = "") -> str:
    """The single best capability domain for `text`, or `default` when nothing matches.

    Ties break on the declaration order of CAPABILITY_DOMAINS, which makes the answer stable
    across runs — a classifier that returns a different domain for the same text would mint a
    fresh gap identity every cycle, the defect this loop already had once.
    """
    hits = count_domains(text)
    if not hits:
        return default
    for domain in CAPABILITY_DOMAINS:
        if hits[domain]:
            return domain
    return default


def is_capability_domain(name: str) -> bool:
    """True when `name` is a capability, not an executor tag or free text."""
    return name in CAPABILITY_DOMAINS
