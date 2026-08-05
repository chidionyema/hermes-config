#!/usr/bin/env python3
"""
Gap-Finding Engine (#3 of the Continuous Learning Build).
Scans the outcome log + capability registry for domains where
Otto repeatedly stumbles and has no policy or skill covering it.

Output: ranked build candidates for human decision.
Does NOT build anything — identifies gaps, surfaces them.
"""

import json
import os
import re
import sys
from collections import Counter
from datetime import datetime

HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
INJECTION_LOG = os.path.join(HERMES_HOME, "logs", "injection-log.jsonl")
POLICY_DIR = os.path.join(HERMES_HOME, "policies")
SKILL_DIR = os.path.join(HERMES_HOME, "skills")
CORPUS_FILE = os.path.join(HERMES_HOME, "logs", "self-regression-corpus.json")
REPORT_DIR = os.path.join(HERMES_HOME, "logs", "maintenance")

# Known capability domains — what Otto can already do
BUILTIN_CAPABILITIES = {
    "terminal": "Run shell commands, build projects, manage processes",
    "file_io": "Read, write, search, and patch files",
    "web_search": "Search the web and extract content",
    "browser": "Navigate and interact with web pages",
    "git": "Commit, push, pull, branch management (via terminal)",
    "skill_management": "Create, update, delete, load skills",
    "cron": "Schedule recurring jobs",
    "delegation": "Spawn subagents for parallel work",
    "memory": "Save and retrieve durable facts across sessions",
    "session_search": "Search past conversations by keyword",
    "code_execution": "Run Python scripts with tool access",
    "vision": "Analyze images via vision models",
    "image_gen": "Generate images from text prompts",
    "tts": "Text-to-speech conversion",
    "messaging": "Send messages across connected platforms",
}


def load_corpus():
    """Load failure corpus."""
    if os.path.exists(CORPUS_FILE):
        with open(CORPUS_FILE) as f:
            return json.load(f)
    return []


def load_injection_log():
    """Load injection log entries."""
    entries = []
    if not os.path.exists(INJECTION_LOG):
        return entries
    with open(INJECTION_LOG) as f:
        for line in f:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def scan_skills():
    """Inventory what skills exist."""
    skills = {}
    if not os.path.isdir(SKILL_DIR):
        return skills
    for cat_dir in os.listdir(SKILL_DIR):
        cat_path = os.path.join(SKILL_DIR, cat_dir)
        if not os.path.isdir(cat_path):
            continue
        for skill_name in os.listdir(cat_path):
            skill_path = os.path.join(cat_path, skill_name)
            if os.path.isdir(skill_path):
                skills[f"{cat_dir}/{skill_name}"] = skill_path
    return skills


def scan_policy_domains():
    """Extract domain coverage from policies."""
    domains = set()
    if not os.path.isdir(POLICY_DIR):
        return domains
    for fname in os.listdir(POLICY_DIR):
        if fname.endswith(".json"):
            path = os.path.join(POLICY_DIR, fname)
            with open(path) as f:
                p = json.load(f)
            trigger = p.get("trigger", "").lower()
            if "terminal" in trigger or "process" in trigger or "build" in trigger:
                domains.add("terminal")
            if "test" in trigger or "verify" in trigger or "pytest" in trigger:
                domains.add("testing")
            if "ask" in trigger or "question" in trigger or "permission" in trigger:
                domains.add("decision-making")
            if "file" in trigger or "read" in trigger or "write" in trigger:
                domains.add("file_io")
            if "api" in trigger or "signature" in trigger:
                domains.add("api_usage")
            if "reflect" in trigger or "correct" in trigger or "learn" in trigger:
                domains.add("self-improvement")
            if "background" in trigger or "sync" in trigger or "timeout" in trigger:
                domains.add("task-management")
            if "kill" in trigger or "replace" in trigger:
                domains.add("process-management")
    return domains


def extract_failure_domains(corpus, injection_log):
    """Extract domain keywords from failure corpus and injection log."""
    domain_counter = Counter()
    
    for entry in corpus:
        text = entry.get("trigger", "") + " " + entry.get("test", "")
        text_lower = text.lower()
        
        # Domain keywords
        if any(w in text_lower for w in ["terminal", "command", "shell", "build"]):
            domain_counter["terminal"] += 1
        if any(w in text_lower for w in ["test", "verify", "pytest", "test suite", "golden"]):
            domain_counter["testing"] += 1
        if any(w in text_lower for w in ["ask", "permission", "question", "should i"]):
            domain_counter["decision-making"] += 1
        if any(w in text_lower for w in ["file", "read", "write", "patch", "search"]):
            domain_counter["file_io"] += 1
        if any(w in text_lower for w in ["api", "signature", "import", "function call"]):
            domain_counter["api_usage"] += 1
        if any(w in text_lower for w in ["background", "sync", "timeout", "wait"]):
            domain_counter["task-management"] += 1
        if any(w in text_lower for w in ["kill", "process", "pid", "stop"]):
            domain_counter["process-management"] += 1
        if any(w in text_lower for w in ["reflect", "correct", "improve", "learn"]):
            domain_counter["self-improvement"] += 1
        if any(w in text_lower for w in ["deploy", "launch", "go-live", "production"]):
            domain_counter["deployment"] += 1
        if any(w in text_lower for w in ["git", "commit", "push", "branch"]):
            domain_counter["git"] += 1
        if any(w in text_lower for w in ["cron", "schedule", "automate", "timer"]):
            domain_counter["automation"] += 1
        if any(w in text_lower for w in ["delegate", "subagent", "parallel"]):
            domain_counter["delegation"] += 1
        if any(w in text_lower for w in ["memory", "remember", "forget", "store"]):
            domain_counter["memory"] += 1
    
    return domain_counter


def find_gaps(failure_domains, policy_domains, skills, corpus):
    """Compare failure domains against coverage. Return ranked gaps."""
    gaps = []
    
    for domain, failure_count in failure_domains.most_common():
        has_policy = domain in policy_domains
        has_skill = domain in skills or any(domain in s for s in skills)
        has_capability = domain in BUILTIN_CAPABILITIES
        
        if has_policy or has_skill or has_capability:
            continue  # Covered
        
        gaps.append({
            "domain": domain,
            "failure_count": failure_count,
            "has_policy": False,
            "has_skill": False,
            "has_builtin": False,
            "suggestion": f"You keep hitting '{domain}' ({failure_count}x in corpus). No policy or skill covers it.",
        })
    
    # Also check: domains where failures exist but skill/policy is incomplete
    for domain, failure_count in failure_domains.most_common():
        has_policy = domain in policy_domains
        has_skill = domain in skills
        if has_policy or has_skill:
            # Has coverage but still failing — quality issue
            gaps.append({
                "domain": domain,
                "failure_count": failure_count,
                "has_policy": has_policy,
                "has_skill": has_skill,
                "has_builtin": domain in BUILTIN_CAPABILITIES,
                "suggestion": f"'{domain}' has {'policy' if has_policy else ''}{' and ' if has_policy and has_skill else ''}{'skill' if has_skill else ''} but still {failure_count} failures. Policy may need tightening.",
            })
    
    return gaps


def build_gap_report(gaps):
    """Build structured gap report."""
    lines = []
    lines.append(f"# Gap-Finding Report — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    
    uncovered = [g for g in gaps if not g["has_policy"] and not g["has_skill"]]
    if uncovered:
        lines.append(f"## 🔴 Uncovered Domains ({len(uncovered)})")
        for g in uncovered:
            lines.append(f"- **{g['domain']}** ({g['failure_count']} failures)")
            lines.append(f"  {g['suggestion']}")
        lines.append("")
    
    weak = [g for g in gaps if g["has_policy"] or g["has_skill"]]
    if weak:
        lines.append(f"## 🟡 Weak Coverage ({len(weak)})")
        for g in weak:
            lines.append(f"- **{g['domain']}** ({g['failure_count']} failures, policy={g['has_policy']}, skill={g['has_skill']})")
            lines.append(f"  {g['suggestion']}")
        lines.append("")
    
    if not uncovered and not weak:
        lines.append("No gaps found. All failure domains have coverage.")
    
    return "\n".join(lines)



def auto_close_gaps(gaps):
    """Bridge gap-finding to Tier 6 GapCloser."""
    try:
        from pathlib import Path
        import os as _os
        HERMES = Path(_os.environ.get('HERMES_HOME', _os.path.expanduser('~/.hermes')))
        sys.path.insert(0, str(HERMES / 'scripts'))
        from auto_close_identity import GapCloser
        gc = GapCloser(HERMES)
        results = {'auto_closed': 0, 'shadow': 0, 'escalated': 0, 'skipped': 0}
        for g in gaps:
            if g.get('has_policy') or g.get('has_skill'):
                results['skipped'] += 1; continue
            gap = gc.identify_gap(g['domain'], g.get('suggestion', g['domain']), g.get('failure_count', 1))
            r = gc.auto_close_if_safe(gap)
            a = r.get('action', '')
            if a == 'auto_promoted': results['auto_closed'] += 1
            elif a == 'shadow_deployed': results['shadow'] += 1
            elif a == 'escalated': results['escalated'] += 1
            else: results['skipped'] += 1
        return results
    except Exception as e:
        return {'error': str(e)}
        
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Gap-Finding Engine")
    parser.add_argument("--run", action="store_true", help="Run gap analysis")
    parser.add_argument("--report", action="store_true", help="Run and save report")
    parser.add_argument("--auto-close", action="store_true",
                       help="Auto-close found gaps by creating provisional policies")
    
    args = parser.parse_args()
    
    if args.run or args.report or args.auto_close:
        corpus = load_corpus()
        injection_log = load_injection_log()
        skills = scan_skills()
        policy_domains = scan_policy_domains()
        failure_domains = extract_failure_domains(corpus, injection_log)
        
        gaps = find_gaps(failure_domains, policy_domains, skills, corpus)
        
        if args.auto_close:
            result = auto_close_gaps(gaps)
            print(f'Auto-close: {result.get("auto_closed",0)} promoted, {result.get("shadow",0)} shadow, {result.get("escalated",0)} escalated')
            if 'error' in result:
                print(f'  Error: {result["error"]}')
        
        if args.report:
            report = build_gap_report(gaps)
            os.makedirs(REPORT_DIR, exist_ok=True)
            report_path = os.path.join(REPORT_DIR, f"gaps-{datetime.now().strftime('%Y-%m-%d')}.md")
            with open(report_path, "w") as f:
                f.write(report)
            print(report)
            print(f"\nReport saved to {report_path}")
        else:
            for g in gaps:
                icon = "🔴" if not g["has_policy"] and not g["has_skill"] else "🟡"
                print(f"{icon} {g['domain']}: {g['failure_count']} failures — {'uncovered' if not g['has_policy'] and not g['has_skill'] else 'weak coverage'}")
        
        return 0
    
    parser.print_help()
    return 0


if __name__ == "__main__":
    main()
