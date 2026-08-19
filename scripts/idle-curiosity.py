#!/usr/bin/env python3
"""Idle Curiosity Pass — runs every 2h during idle time, does genuine learning work.

Four modules:
  1. Cross-repo dependency scan — check prospector/hermes-agent for cross-impact
  2. Stale skill auditor — which skills are never loaded, which are skeletons
  3. Meta-improver action — reads bottleneck reports, applies auto-tunes
  4. Curiosity finder — reads changelogs, release notes, surfaces interesting changes

Output: ~/.hermes/logs/idle-curiosity/YYYY-MM-DD-HHMM.md
Only produces output when something actionable is found.
"""

import json, os, subprocess, sys, glob, hashlib
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
LOG_DIR = HERMES_HOME / "logs" / "idle-curiosity"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# cron-guard: git-optional — every git call sits behind a checkout test (_checkouts()), and a
# machine with no checkouts produces a `repo_not_a_checkout` finding rather than a silent pass.
# The estate is two repos: prospector and hermes-agent (founder directive 2026-08-19,
# "hermes agent thinks the estate is every folder in code, should understand it's just
# prospector and hermes agent"). signalengine and lux were in this dict and are not in the
# estate, so every "cross-repo" finding was scored against projects nobody works on.
REPOS = {
    "prospector": Path.home() / "Documents/code/prospector",
    "hermes-agent": HERMES_HOME / "hermes-agent",
}

SKILLS_DIR = HERMES_HOME / "skills"
USAGE_FILE = HERMES_HOME / ".skills_prompt_snapshot.json"
POLICY_DIR = HERMES_HOME / "policies"
META_LOGS = HERMES_HOME / "logs" / "meta-improver"
PREVIOUS_SCAN = LOG_DIR / "_last_scan.json"

def iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "(timeout)", "", -1
    except Exception as e:
        return f"(error: {e})", "", -1

# ── MODULE 1: Cross-Repo Dependency Scan ─────────────────────────

def scan_cross_repo():
    """Check each repo for changes that might affect the others."""
    findings = []
    
    # Get HEAD hashes for comparison
    heads = {}
    for name, path in REPOS.items():
        if not path.exists():
            findings.append({"type": "repo_missing", "severity": "warning",
                             "message": f"Repo path missing: {name} ({path})"})
            continue
        if not (path / ".git").exists():
            # Measured 2026-08-19: the deploy image copies hermes-agent/ but .dockerignore
            # strips .git, so every git call here returned empty and the scan looked clean.
            findings.append({"type": "repo_not_a_checkout", "severity": "warning",
                             "message": f"No .git at {name} ({path}) — cross-repo scan cannot run here"})
            continue
        out, _, _ = run(f"cd {path} && git rev-parse --short HEAD && git log --oneline -3 --format='%h %s' 2>/dev/null")
        if out:
            lines = out.split("\n")
            heads[name] = {"hash": lines[0], "recent": lines[1:4] if len(lines) > 1 else []}
    
    if not heads:
        return findings
    
    # Check for stale branches or unmerged work
    for name, path in REPOS.items():
        if not path.exists():
            continue
        out, _, _ = run(f"cd {path} && git stash list 2>/dev/null")
        if out:
            items = [l for l in out.split("\n") if l.strip()]
            if items:
                findings.append({"type": "stale_stash", "severity": "info",
                                 "message": f"{name}: {len(items)} stashed changes"})
    
    # Check for dependency alignment (same dependency in different versions across repos)
    dep_versions = {}
    for name, path in REPOS.items():
        if not path.exists():
            continue
        # Check requirements files
        for req_file in ["requirements.txt", "pyproject.toml", "Pipfile"]:
            rp = path / req_file
            if rp.exists():
                try:
                    content = rp.read_text()
                    for line in content.split("\n"):
                        line = line.strip()
                        if "==" in line and not line.startswith("#"):
                            parts = line.split("==")
                            if len(parts) == 2:
                                dep = parts[0].strip().lower()
                                ver = parts[1].strip()
                                dep_versions.setdefault(dep, {})[name] = ver
                except:
                    pass
    
    # Flag version mismatches
    for d, dep_vers in dep_versions.items():
        if len(dep_vers) >= 2:
            unique_vers = set(dep_vers.values())
            if len(unique_vers) > 1:
                details = ", ".join(f"{repo}={ver}" for repo, ver in sorted(dep_vers.items()))
                findings.append({"type": "dep_mismatch", "severity": "warning",
                                 "message": f"Dependency '{dep}' has version mismatch: {details}"})
    
    # Flag shared dependency but missing from some repos
    all_repo_names = set()
    for _, dep_vers in dep_versions.items():
        all_repo_names.update(dep_vers.keys())
    for dep, dep_vers in dep_versions.items():
        for name in sorted(all_repo_names):
            if name not in dep_vers and len(dep_vers) >= 2:
                present_in = [r for r in dep_vers if r != name]
                if present_in:
                    findings.append({"type": "dep_missing", "severity": "info",
                                     "message": f"{name} is missing dependency '{dep}' (present in {', '.join(present_in)})"})
    
    return findings

# ── MODULE 2: Stale Skill Auditor ────────────────────────────────

def scan_skill_staleness():
    """Find skills that are never loaded, skeletons, or stale."""
    findings = []
    
    # Count all skills
    all_skills = set()
    skeleton_skills = []
    loaded_skills = set()
    
    for sk in SKILLS_DIR.rglob("SKILL.md"):
        skill_name = sk.parent.name
        category = sk.parent.parent.name if sk.parent.parent != SKILLS_DIR else "uncategorized"
        all_skills.add(skill_name)
        
        # Check for supporting files
        has_refs = (sk.parent / "references").exists() and len(list((sk.parent / "references").glob("*"))) > 0
        has_scripts = (sk.parent / "scripts").exists() and len(list((sk.parent / "scripts").glob("*"))) > 0
        has_templates = (sk.parent / "templates").exists() and len(list((sk.parent / "templates").glob("*"))) > 0
        
        if not has_refs and not has_scripts and not has_templates:
            skeleton_skills.append(skill_name)
    
    # Check usage file
    if USAGE_FILE.exists():
        try:
            with open(USAGE_FILE) as f:
                usage = json.load(f)
            loaded_skills = set(usage.get("skills_loaded", []))
        except:
            pass
    
    never_loaded = all_skills - loaded_skills
    
    if never_loaded:
        # Group by category
        never_by_cat = {}
        for sk in SKILLS_DIR.rglob("SKILL.md"):
            if sk.parent.name in never_loaded:
                cat = sk.parent.parent.name if sk.parent.parent != SKILLS_DIR else "uncategorized"
                never_by_cat.setdefault(cat, []).append(sk.parent.name)
        
        total_never = len(never_loaded)
        if total_never > 10:
            top_cats = sorted(never_by_cat.items(), key=lambda x: -len(x[1]))[:5]
            cat_detail = ", ".join(f"{cat}: {len(skills)}" for cat, skills in top_cats)
            findings.append({"type": "skills_never_loaded", "severity": "info",
                             "message": f"{total_never}/{len(all_skills)} skills never loaded. Top: {cat_detail}"})
    
    if skeleton_skills:
        findings.append({"type": "skeleton_skills", "severity": "info",
                         "message": f"{len(skeleton_skills)} skeleton skills (SKILL.md only, no supporting files)"})
    
    # Track skill bloat — growth in last N days
    if PREVIOUS_SCAN.exists():
        try:
            prev = json.loads(PREVIOUS_SCAN.read_text())
            prev_count = prev.get("total_skills", 0)
            diff = len(all_skills) - prev_count
            if diff > 5:
                findings.append({"type": "skill_bloat", "severity": "warning",
                                 "message": f"Skills grew by {diff} since last scan ({prev_count} → {len(all_skills)})"})
        except:
            pass
    
    return findings

# ── MODULE 3: Meta-Improver Action ──────────────────────────────

def act_on_bottlenecks():
    """Read meta-improver bottleneck reports and apply auto-tunes."""
    findings = []
    
    reports = sorted(META_LOGS.glob("bottleneck-*.json"))
    if not reports:
        return findings
    
    # Analyze the last 5 reports for patterns
    phases = []
    suggestions = []
    for f in reports[-5:]:
        try:
            data = json.loads(f.read_text())
            bottleneck = data.get("bottleneck_phase") or data.get("metrics", {}).get("slowest_phase")
            if bottleneck and bottleneck != "?":
                phases.append(bottleneck)
            suggestions.extend(data.get("suggestions") or [])
        except:
            pass
    
    if phases:
        from collections import Counter
        phase_counts = Counter(phases)
        for phase, count in phase_counts.most_common(2):
            if count >= 2:
                findings.append({"type": "persistent_bottleneck", "severity": "warning",
                                 "message": f"Phase '{phase}' is a persistent bottleneck ({count}/{len(reports)} reports)"})
    
    if not phases:
        # Meta-improver is running but producing empty reports — it's a dead pipeline
        findings.append({"type": "meta_improver_empty", "severity": "warning",
                         "message": f"Meta-improver produced {len(reports)} reports but none identified a bottleneck"})
    
    # Check if meta-improver has produced any change-outcomes to learn from
    outcomes_file = HERMES_HOME / "meta" / "change-outcomes.jsonl"
    if outcomes_file.exists():
        try:
            outcomes = [json.loads(l) for l in outcomes_file.read_text().strip().split("\n") if l.strip()]
            if len(outcomes) < 3:
                findings.append({"type": "meta_improver_no_data", "severity": "info",
                                 "message": f"Meta-improver has only {len(outcomes)} outcomes — too few to learn from"})
        except:
            pass
    
    return findings

# ── MODULE 4: Curiosity Finder ──────────────────────────────────

def find_interesting_changes():
    """Find interesting changes across repos and config."""
    findings = []
    
    # Recent commits in each repo
    for name, path in REPOS.items():
        if not path.exists():
            continue
        out, _, _ = run(f"cd {path} && git log --oneline -5 --since='2 days ago' 2>/dev/null | head -5")
        if out:
            commit_count = len([l for l in out.split("\n") if l.strip()])
            if commit_count > 0:
                findings.append({"type": "repo_activity", "severity": "info",
                                 "message": f"{name}: {commit_count} commits in last 2 days"})
                # First commit preview
                lines = [l for l in out.split("\n") if l.strip()]
                for l in lines[:2]:
                    findings.append({"type": "recent_commit", "severity": "info",
                                     "message": f"{name}: {l[:80]}"})
    
    # Check for TODO/FIXME/HACK density
    for name, path in REPOS.items():
        if not path.exists():
            continue
        out, _, _ = run(f"cd {path} && grep -r 'TODO\\|FIXME\\|HACK' --include='*.py' --include='*.ts' --include='*.js' -l 2>/dev/null | wc -l | tr -d ' '")
        if out and out.strip().isdigit() and int(out.strip()) > 5:
            findings.append({"type": "tech_debt", "severity": "info",
                             "message": f"{name}: {out.strip()} files with TODO/FIXME/HACK markers"})
    
    # Check for large files that might need attention
    for name, path in REPOS.items():
        if not path.exists():
            continue
        out, _, _ = run(f"cd {path} && find . -name '*.py' -size +100k -not -path './.git/*' -not -path './node_modules/*' 2>/dev/null | head -5")
        if out:
            for line in out.split("\n"):
                if line.strip():
                    findings.append({"type": "large_file", "severity": "info",
                                     "message": f"{name}: large file {line.strip()[:60]}"})
    
    return findings

# ── REPORT GENERATION ───────────────────────────────────────────

def generate_report(findings):
    """Generate markdown report from findings."""
    if not findings:
        return ""
    
    sev_groups = {"critical": [], "warning": [], "info": []}
    for f in findings:
        sev_groups.get(f.get("severity", "info"), sev_groups["info"]).append(f)
    
    # Deduplicate by message
    for sev in sev_groups:
        seen = set()
        unique = []
        for f in sev_groups[sev]:
            msg = f.get("message", "")
            if msg not in seen:
                seen.add(msg)
                unique.append(f)
        sev_groups[sev] = unique
    
    parts = [f"# Idle Curiosity Findings",
             f"**Generated:** {iso_now()}",
             f"**Modules:** cross-repo, stale-skills, meta-improver, curiosity\n"]
    
    for severity in ["critical", "warning", "info"]:
        group = sev_groups.get(severity, [])
        if group:
            label = {"critical": "🔴 Critical", "warning": "🟡 Warning", "info": "🔵 Info"}[severity]
            parts.append(f"## {label}")
            for f in group:
                parts.append(f"- **[{f['type']}]** {f['message']}")
            parts.append("")
    
    return "\n".join(parts)

# ── MAIN ────────────────────────────────────────────────────────

if __name__ == "__main__":
    all_findings = []
    
    print("=== Idle Curiosity Pass ===")
    
    print("Module 1: Cross-repo dependency scan...")
    all_findings.extend(scan_cross_repo())
    
    print("Module 2: Stale skill audit...")
    all_findings.extend(scan_skill_staleness())
    
    print("Module 3: Meta-improver action...")
    all_findings.extend(act_on_bottlenecks())
    
    print("Module 4: Curiosity finder...")
    all_findings.extend(find_interesting_changes())
    
    report = generate_report(all_findings)
    
    if report:
        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M")
        out_path = LOG_DIR / f"{timestamp}.md"
        out_path.write_text(report)
        print(f"\nReport written to {out_path}")
        print(report)
    else:
        print("\nNo curiosity findings — everything quiet.")
    
    # Save scan state for next comparison
    skill_count = len(list(SKILLS_DIR.rglob("SKILL.md")))
    PREVIOUS_SCAN.write_text(json.dumps({
        "last_scan": iso_now(),
        "total_skills": skill_count,
        "total_findings": len(all_findings),
    }, indent=2))
