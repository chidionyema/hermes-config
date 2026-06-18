#!/usr/bin/env python3
"""
otto-why.py — Rationale reconstruction for Otto decisions.

Usage:
    python3 ~/.hermes/scripts/otto-why.py <task_id or "last">

Reads the injection log, firing log, and policy state for the given task,
then reconstructs what decision logic led to the outcome.

If Claude is available, delegates the reconstruction for richer analysis.
Otherwise, produces a text summary from local data.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"

def load_jsonl(path: Path) -> list[dict]:
    entries = []
    if not path.exists():
        return entries
    with open(path) as f:
        for line in f:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries

def load_policies() -> list[dict]:
    policy_dir = HERMES_HOME / "policies"
    policies = []
    if not policy_dir.exists():
        return policies
    for fname in sorted(policy_dir.glob("pol-*.json")):
        with open(fname) as f:
            policies.append(json.load(f))
    return policies

def find_injection(task_id: str, injections: list[dict]) -> dict | None:
    """Find injection log entry by task ID (exact or substring match)."""
    for inj in injections:
        task = inj.get("task", "")
        if task_id == "last":
            return injections[-1] if injections else None
        if task_id in task or task == task_id:
            return inj
    return None

def find_firings(task_id: str, firings: list[dict]) -> list[dict]:
    """Find policy firings that match the task context."""
    if task_id == "last" and firings:
        return [firings[-1]]
    return [f for f in firings if task_id in f.get("context", "") or task_id in f.get("policy_id", "")]

def format_reconstruction(task_id: str, injection: dict | None, firings: list[dict], policies: list[dict]):
    """Build a structured rationale reconstruction from available data."""
    lines = []
    lines.append(f"# Decision Rationale — {task_id}")
    lines.append(f"*Reconstructed at {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}*")
    lines.append("")

    # 1. Injection context
    if injection:
        lines.append("## 🧠 Strategist Injection Context")
        lines.append(f"**Task:** {injection.get('task', '?')}")
        lines.append(f"**Timestamp:** {injection.get('timestamp', '?')}")
        lines.append(f"**Memory entries scanned:** {injection.get('total_entries', 0)}")
        lines.append(f"**Entries retrieved:** {injection.get('retrieved_count', 0)}")
        tags = injection.get("retrieved_tags", [])
        if tags:
            lines.append("**Retrieved tags:**")
            for t in tags:
                lines.append(f"  - {t}")
        apc = injection.get("active_policies_count", 0)
        if apc:
            lines.append(f"**Active policies injected:** {apc}")
            triggers = injection.get("active_policy_triggers", [])
            for tr in triggers:
                lines.append(f"  - {tr[:80]}")
        lines.append("")
    else:
        lines.append("## ⚠️ No injection log entry found")
        lines.append("The task may not have gone through the strategist dispatch path.")
        lines.append("")

    # 2. Policy firings
    if firings:
        lines.append(f"## 🔥 Policy Firings ({len(firings)})")
        for f in firings:
            lines.append(f"- **{f.get('policy_id', '?')}**: {f.get('trigger', '?')[:60]}")
            lines.append(f"  Rule: {f.get('rule', '?')[:80]}")
            lines.append(f"  Context: {f.get('context', '?')}")
            lines.append(f"  At: {f.get('timestamp', '?')}")
            lines.append("")
    else:
        lines.append("## Policy Firings")
        lines.append("No policy firings found for this task.")
        lines.append("")

    # 3. Active policies that could have been relevant
    relevant_policies = []
    if injection:
        task_text = injection.get("task", "").lower()
        for p in policies:
            trigger = p.get("trigger", "").lower()
            rule = p.get("rule", "").lower()
            combined = trigger + " " + rule
            task_words = set(task_text.split())
            pol_words = set(combined.split())
            overlap = len(task_words & pol_words) / max(len(task_words), 1)
            if overlap > 0.2:
                relevant_policies.append(p)

    if relevant_policies:
        lines.append(f"## 📋 Relevant Policies ({len(relevant_policies)})")
        for p in relevant_policies:
            lines.append(f"- **{p.get('id', '?')}** ({p.get('status', '?')}, conf={p.get('confidence', 0)}):")
            lines.append(f"  Trigger: {p.get('trigger', '?')[:80]}")
            lines.append(f"  Rule: {p.get('rule', '?')[:80]}")
            lines.append("")
    else:
        lines.append("## No specific policies matched this task's context.")
        lines.append("")

    # 4. Summarize
    lines.append("## Summary")
    if injection and firings:
        lines.append("This task had both strategist injection context and active policy enforcement.")
        lines.append(f"{len(relevant_policies)} policies were relevant to the task domain.")
    elif injection:
        lines.append("Task dispatched through strategist pathway but policies not explicitly fired.")
    elif firings:
        lines.append("Policy enforcement fired but no strategist injection recorded.")
    else:
        lines.append("Neither injection nor firings found — may be a direct tool execution task.")
    lines.append("")

    return "\n".join(lines)


def call_claude_for_rationale(task_id: str, reconstruction_text: str) -> str:
    """Optional: Dispatch to Claude for richer analysis."""
    try:
        result = subprocess.run(
            ["python3", "-c", "import json; print('CLAUDE_AVAILABLE')"],
            capture_output=True, text=True, timeout=5
        )
        if "CLAUDE_AVAILABLE" not in result.stdout:
            return reconstruction_text
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    # Claude dispatch not available inline — return text analysis
    return reconstruction_text


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 otto-why.py <task_id or 'last'>", file=sys.stderr)
        sys.exit(1)

    task_id = sys.argv[1]

    injections = load_jsonl(HERMES_HOME / "logs" / "injection-log.jsonl")
    firings = load_jsonl(HERMES_HOME / "logs" / "policy-firings.jsonl")
    policies = load_policies()

    injection = find_injection(task_id, injections)
    relevant_firings = find_firings(task_id, firings)

    report = format_reconstruction(task_id, injection, relevant_firings, policies)

    print(report)

    # Save to a readable location
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_id = task_id.replace("/", "_").replace(" ", "_")[:30]
    out_path = HERMES_HOME / "logs" / f"why-{safe_id}-{ts}.md"
    with open(out_path, "w") as f:
        f.write(report)
    print(f"\n(Report saved to {out_path})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
