#!/usr/bin/env python3
"""otto-correction-gate.py — structural enforcement for the most common dropped balls.

The hard lesson: policies (documentation) don't enforce. Gates do. This gate
catches the patterns that have burned us most often:

  1. User-stated-value violation: the user gave a specific value (number, schedule,
     filename) and the agent's response contains a counter-proposal ("too aggressive",
     "let's do X instead", "what about Y"). This is the #1 dropped-ball pattern
     in this session. Hard block: any counter-proposal in the same turn as a
     user-given value is a violation.

  2. Cron job creation without a verification probe. Every cron job created
     must be run standalone at least 3 times before the agent can claim "works."

  3. Edit-without-test on cron-touching files (otto-dispatch.py, hermes_queue.py,
     alert-resolver.py, idle-learning-run.sh, repo-health-check.py). Any edit
     to these files requires a full cycle test before "shipped" can be claimed.

Usage:
  python3 otto-correction-gate.py check <action-description>

Exit codes:
  0 = PASS (proceed)
  1 = BLOCK (one or more gates violated; agent must fix and retry)
  2 = NOT-APPLICABLE (action doesn't match any gate pattern)

The gate is whitelist + pattern. When a new failure class emerges, add a
CHECK FUNCTION here — not a policy file. The skill explicitly says
"policies alone are not enforcement."
"""
from __future__ import annotations
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERMES = Path.home() / ".hermes"
LOG = HERMES / "logs" / "correction-gate.jsonl"
LOG.parent.mkdir(parents=True, exist_ok=True)

# Phrases that indicate the agent is about to re-litigate a user-stated value.
# Whitelist: things like "shall I proceed?" are still OK if the value is NOT specific.
COUNTER_PROPOSAL_PATTERNS = [
    (r"\btoo aggressive\b", "user gave a value, agent called it 'too aggressive'"),
    (r"\blet'?s (do|try|use) (a |an |the )?(\d|\w+)\b(?!.*you (asked|said|wanted))",
     "agent proposed alternative value after user gave a specific value"),
    (r"\bwhat about\b.*\?", "agent counter-proposed to a user-stated value"),
    (r"\binstead,? (do|use|try)\b", "agent counter-proposed to a user-stated value"),
    (r"\b(hourly|daily|every \d+\s*m) would be\b(?!.*you (asked|said|wanted))",
     "agent suggested different cadence after user gave one"),
    (r"\bdo you want me to\b.*\?", "agent asked permission after user gave a directive"),
]

# Cron-touching files. Edits to these without a verification test = structural risk.
CRON_TOUCHING_FILES = {
    "otto-dispatch.py", "hermes_queue.py", "queue-curate.sh", "alert-resolver.py",
    "idle-learning-run.sh", "repo-health-check.py", "watchdog.py",
    "improvement-probe.sh", "known_classes.py", "hermes_fingerprint.py",
    "signal-engine-daemon-watchdog.sh", "memory-capacity-probe.sh",
    "uncommitted-watch.sh",
}


def log(outcome: str, action: str, violations: list[str]) -> None:
    try:
        with open(LOG, "a") as f:
            f.write(json.dumps({
                "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "outcome": outcome,
                "action": action[:300],
                "violations": violations,
            }) + "\n")
    except Exception:
        pass


def check_counter_proposal(action: str) -> list[str]:
    """Block counter-proposals when the action text contains a user-stated value
    (a number followed by a unit, or quoted string)."""
    # Detect user-stated value in the action
    has_specific_value = bool(re.search(
        r"\b(every\s*\d+\s*(m|min|minute|h|hour|day)|"
        r"set (it|to) (every|\d)|"
        r"\"[^\"]+\"|"
        r"schedule.*?every\s+\d)",
        action, re.IGNORECASE))
    if not has_specific_value:
        return []
    violations = []
    for pat, why in COUNTER_PROPOSAL_PATTERNS:
        if re.search(pat, action, re.IGNORECASE):
            violations.append(f"counter-proposal: {why}")
    return violations


def check_cron_edit_without_test(action: str) -> list[str]:
    """If action describes editing a cron-touching file, require a verification
    probe mention in the same or next action."""
    files_pattern = "|".join(re.escape(f) for f in CRON_TOUCHING_FILES)
    # Match verb-then-file OR file-then-verb. Note: no trailing \b on the file
    # pattern because \b doesn't anchor at hyphens, and the file names end in
    # .py / .sh which has its own boundary.
    edit_match = re.search(
        r"\b(edit|patch|modify|fix|change|update)\b[^.\n]*?(?:" + files_pattern + r")|"
        r"(?:" + files_pattern + r")[^.\n]*?\b(edit|patch|modify|fix|change|update)\b",
        action, re.IGNORECASE)
    if not edit_match:
        return []
    if re.search(r"\b(verified|tested|probe|standalone test|full cycle|2 consecutive|on 2 consecutive)\b",
                 action, re.IGNORECASE):
        return []
    return [f"edit to cron-touching file without verification probe mentioned "
            f"(action: '{action[:80]}')"]


def check_orphan_spawn(action: str) -> list[str]:
    """If the action spawns a long-running process, require a kill/cleanup mention."""
    spawn_match = re.search(r"\b(background|spawn|nohup|&\s*$|pytest|hermes send|daemon)\b",
                            action, re.IGNORECASE)
    if not spawn_match:
        return []
    if re.search(r"\b(kill|trap|cleanup|on-exit)\b", action, re.IGNORECASE):
        return []
    return [f"spawn detected ({spawn_match.group(0)}) without explicit cleanup/kill mention"]


CHECKS = [check_counter_proposal, check_cron_edit_without_test, check_orphan_spawn]


def main() -> int:
    if len(sys.argv) < 3 or sys.argv[1] != "check":
        print("usage: otto-correction-gate.py check <action-description>")
        return 2
    action = sys.argv[2]
    violations: list[str] = []
    for check in CHECKS:
        violations.extend(check(action))
    if violations:
        log("BLOCK", action, violations)
        print("GATE BLOCKED — fix these before proceeding:")
        for v in violations:
            print(f"  ✗ {v}")
        return 1
    log("PASS", action, [])
    print("GATE PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
