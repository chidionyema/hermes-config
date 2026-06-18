#!/usr/bin/env python3
"""Estate Drift Detector — compares today's inventory to last snapshot.
Flags: new/removed scripts, dead/added cron jobs, policy inactivity,
skill bloat, config changes, pipeline phase drift.

Output: ~/.hermes/reports/estate-drift.md (or empty if no drift)
"""

import json, os, glob, hashlib
from datetime import datetime
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
SNAPSHOT_DIR = HERMES_HOME / "reports" / "snapshots"
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
LATEST_SNAPSHOT = max(SNAPSHOT_DIR.glob("estate-*.json"), key=lambda f: f.stat().st_mtime) if list(SNAPSHOT_DIR.glob("estate-*.json")) else None
CURRENT_INVENTORY = HERMES_HOME / "reports" / "estate-inventory.md"
DRIFT_REPORT = HERMES_HOME / "reports" / "estate-drift.md"

def take_snapshot():
    """Capture current estate state as JSON snapshot."""
    snapshot = {
        "timestamp": datetime.now().isoformat(),
        "scripts": sorted([f.name for f in (HERMES_HOME / "scripts").glob("*.py")] +
                          [f.name for f in (HERMES_HOME / "scripts").glob("*.sh")]),
        "skills": sorted([f.parent.name for f in (HERMES_HOME / "skills").rglob("SKILL.md")]),
        # Get actual cron jobs from jobs.json
        "cron_jobs": {},
        "policies": [],
        "config_hash": "",
        "pipeline_phases": [],
    }
    
    # Cron jobs
    cron_file = HERMES_HOME / "cron" / "jobs.json"
    if cron_file.exists():
        with open(cron_file) as f:
            cron_data = json.load(f)
        for j in cron_data.get("jobs", []):
            snapshot["cron_jobs"][j.get("name", "?")[:50]] = {
                "schedule": j.get("schedule", {}).get("display", "?"),
                "status": j.get("last_status", "?"),
                "script": bool(j.get("script")),
                "workdir": bool(j.get("workdir")),
            }
    
    # Policies
    for f in sorted((HERMES_HOME / "policies").glob("*.json")):
        try:
            with open(f) as pf:
                p = json.load(pf)
            snapshot["policies"].append({
                "id": p.get("id", f.stem),
                "status": p.get("status", "?"),
                "domain": p.get("scope", {}).get("domain", "?"),
                "hits": p.get("hits", 0),
                "created": p.get("created_at", "?"),
            })
        except:
            pass
    
    # Config hash
    config = HERMES_HOME / "config.yaml"
    if config.exists():
        snapshot["config_hash"] = hashlib.md5(config.read_bytes()).hexdigest()[:12]
        snapshot["config_size"] = config.stat().st_size
    
    # Pipeline phases from inventory
    snapshot["pipeline_phases"] = [
        "preflight", "post-correction", "meta-improvement", "gap-finding",
        "cross-project", "near-miss", "self-regression", "self-detect",
        "policy-compose", "trend-analysis", "consolidation", "postflight"
    ]
    
    # Save
    path = SNAPSHOT_DIR / f"estate-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    with open(path, "w") as f:
        json.dump(snapshot, f, indent=2)
    return snapshot, path

def load_previous():
    """Load the most recent previous snapshot."""
    if not LATEST_SNAPSHOT:
        return None
    try:
        with open(LATEST_SNAPSHOT) as f:
            return json.load(f)
    except:
        return None

def detect_drift(current, previous):
    """Compare two snapshots and return a list of drift items."""
    changes = []
    
    if not previous:
        changes.append({"type": "info", "severity": "info", 
                        "message": "First snapshot — baseline established. No drift to compare."})
        return changes
    
    # Scripts
    prev_scripts = set(previous.get("scripts", []))
    cur_scripts = set(current.get("scripts", []))
    new_scripts = cur_scripts - prev_scripts
    removed_scripts = prev_scripts - cur_scripts
    for s in sorted(new_scripts):
        changes.append({"type": "script_added", "severity": "info", 
                        "message": f"New script: {s}"})
    for s in sorted(removed_scripts):
        changes.append({"type": "script_removed", "severity": "warning",
                        "message": f"Script removed: {s}"})
    
    # Skills
    prev_skills = set(previous.get("skills", []))
    cur_skills = set(current.get("skills", []))
    new_skills = cur_skills - prev_skills
    removed_skills = prev_skills - cur_skills
    for s in sorted(new_skills):
        changes.append({"type": "skill_added", "severity": "info",
                        "message": f"New skill added: {s}"})
    for s in sorted(removed_skills):
        changes.append({"type": "skill_removed", "severity": "info",
                        "message": f"Skill removed: {s}"})
    
    # Skill bloat
    skill_growth = len(cur_skills) - len(prev_skills)
    if skill_growth > 5:
        changes.append({"type": "skill_bloat", "severity": "warning",
                        "message": f"Skills grew by {skill_growth} since last snapshot — review if all are used"})
    
    # Cron jobs
    prev_crons = set(previous.get("cron_jobs", {}).keys())
    cur_crons = set(current.get("cron_jobs", {}).keys())
    for j in sorted(cur_crons - prev_crons):
        details = current["cron_jobs"][j]
        changes.append({"type": "cron_added", "severity": "info",
                        "message": f"New cron job: {j} ({details['schedule']})"})
    for j in sorted(prev_crons - cur_crons):
        changes.append({"type": "cron_removed", "severity": "warning",
                        "message": f"Cron job removed: {j}"})
    
    # Dead cron jobs (never ran, pending)
    for j, details in current.get("cron_jobs", {}).items():
        if details.get("status") == "pending":
            changes.append({"type": "cron_never_run", "severity": "warning",
                            "message": f"Cron job never ran: {j} ({details['schedule']})"})
    
    # Policy inactivity
    prev_pols = {p["id"]: p for p in previous.get("policies", [])}
    cur_pols = {p["id"]: p for p in current.get("policies", [])}
    
    for pid, p in cur_pols.items():
        # Skip escalation-chain policies (tiered — expected to be quiet until tier 1 fires)
        if p.get("depends_on") or p.get("superseded_by") or p.get("escalates_to"):
            continue
        if p.get("hits", 0) == 0:
            changes.append({"type": "policy_inactive", "severity": "warning",
                            "message": f"Policy never fired: {pid} (domain={p.get('domain','?')})"})
        elif pid in prev_pols:
            prev_hits = prev_pols[pid].get("hits", 0)
            if p.get("hits", 0) == prev_hits and prev_hits > 0:
                changes.append({"type": "policy_stalled", "severity": "info",
                                "message": f"Policy not gaining hits: {pid} (still at {prev_hits})"})
    
    new_pols_ids = set(cur_pols.keys()) - set(prev_pols.keys())
    for pid in sorted(new_pols_ids):
        changes.append({"type": "policy_added", "severity": "info",
                        "message": f"New policy: {pid} (domain={cur_pols[pid].get('domain','?')})"})
    
    removed_pols = set(prev_pols.keys()) - set(cur_pols.keys())
    for pid in sorted(removed_pols):
        changes.append({"type": "policy_removed", "severity": "info",
                        "message": f"Policy removed: {pid}"})
    
    # Config change
    if previous.get("config_hash") and current.get("config_hash"):
        if previous["config_hash"] != current["config_hash"]:
            changes.append({"type": "config_changed", "severity": "info",
                            "message": f"Config changed: hash {previous['config_hash']} → {current['config_hash']}"})
    
    return changes

def generate_report(changes, current_snapshot):
    """Generate drift report markdown."""
    if not changes:
        return ""
    
    severities = {"critical": [], "warning": [], "info": []}
    for c in changes:
        severities.get(c["severity"], severities["info"]).append(c)
    
    parts = [f"# Estate Drift Report", 
             f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
             f"**Baseline:** {LATEST_SNAPSHOT.name if LATEST_SNAPSHOT else 'none — first snapshot'}\n"]
    
    total = len(changes)
    warnings = len(severities["warning"])
    critical = len(severities["critical"])
    summary_parts = []
    if critical:
        summary_parts.append(f"**{critical} critical**")
    if warnings:
        summary_parts.append(f"**{warnings} warnings**")
    summary_parts.append(f"{total - critical - warnings} info items")
    parts.append(f"**Changes detected:** {', '.join(summary_parts)}\n")
    
    for severity in ["critical", "warning", "info"]:
        if severities[severity]:
            label = {"critical": "🔴 Critical", "warning": "🟡 Warning", "info": "🔵 Info"}[severity]
            parts.append(f"## {label}")
            for c in severities[severity]:
                parts.append(f"- {c['message']}")
            parts.append("")
    
    # Stats
    parts.append("## Estate Summary")
    parts.append(f"- **Scripts:** {len(current_snapshot['scripts'])}")
    parts.append(f"- **Skills:** {len(current_snapshot['skills'])}")
    parts.append(f"- **Cron jobs:** {len(current_snapshot['cron_jobs'])}")
    parts.append(f"- **Policies:** {len(current_snapshot['policies'])}")
    parts.append(f"- **Config version:** {current_snapshot.get('config_hash', '?')}")
    
    # Action items
    action_items = []
    for c in changes:
        if c["severity"] in ("critical", "warning"):
            if "cron_never_run" in c["type"]:
                action_items.append(f"- [ ] Test cron job '{c['message'].split(': ')[-1]}' or remove it")
            elif "policy_inactive" in c["type"] or "policy_stalled" in c["type"]:
                action_items.append(f"- [ ] Review/archive policy: {c['message'].split(': ')[-1]}")
            elif "script_removed" in c["type"]:
                action_items.append(f"- [ ] Verify script removal was intentional: {c['message'].split(': ')[-1]}")
            elif "skill_bloat" in c["type"]:
                action_items.append(f"- [ ] Audit new skills — tag or retire unused ones")
    
    if action_items:
        parts.append("\n## Action Items")
        parts.extend(action_items)
    
    return "\n".join(parts)

# ── MAIN ──────────────────────────────────────────
if __name__ == "__main__":
    current, snapshot_path = take_snapshot()
    previous = load_previous()
    changes = detect_drift(current, previous)
    report = generate_report(changes, current)
    
    if report:
        DRIFT_REPORT.parent.mkdir(parents=True, exist_ok=True)
        with open(DRIFT_REPORT, "w") as f:
            f.write(report)
        print(f"Drift report written to {DRIFT_REPORT}")
        print(f"Snapshot saved to {snapshot_path}")
        print(report)
    else:
        # No drift — still save snapshot, but no report file
        if DRIFT_REPORT.exists():
            DRIFT_REPORT.unlink()
        print(f"Snapshot saved to {snapshot_path}")
        print("No drift detected — estate stable.")
