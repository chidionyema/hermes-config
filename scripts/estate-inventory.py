
#!/usr/bin/env python3
"""Estate Inventory — complete map of every component.
Run daily, output to ~/.hermes/reports/estate-inventory.md
"""
import json, os, glob, subprocess, hashlib
from datetime import datetime
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))

def run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode
    except: return "", -1

def fmt_size(path):
    if path.exists():
        size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1024
        return f"{size:.0f}KB"
    return "0KB"

def count_files(path, pattern="*"):
    if not path.exists():
        return 0
    return len(list(path.rglob(pattern)))

def section(title, body):
    return f"\n## {title}\n\n{body}\n"

# ── 1. HERMES CONFIG ─────────────────────────────────────────
lines = ["### Hermes Agent\n"]
ver, _ = run("hermes --version 2>/dev/null || echo 'unknown'")
lines.append(f"- **Version:** {ver}")
lines.append(f"- **Config:** {HERMES_HOME}/config.yaml ({(HERMES_HOME/'config.yaml').stat().st_size if (HERMES_HOME/'config.yaml').exists() else 0} bytes)")
lines.append(f"- **Profile:** default")
detect, _ = run("cat ~/.hermes/config.yaml | grep -c 'default_model'")
lines.append(f"- **Models configured:** {detect or 'check config'}")
lines.append(f"- **Skills count:** {count_files(HERMES_HOME/'skills', 'SKILL.md')}")
lines.append(f"- **Plugins:** {count_files(HERMES_HOME/'plugins', '*.py')}")
lines.append(f"- **Cron jobs:** {count_files(HERMES_HOME/'cron', 'jobs.json')} (1 file = {len(json.loads((HERMES_HOME/'cron/jobs.json').read_text()).get('jobs',[])) if (HERMES_HOME/'cron/jobs.json').exists() else 0} jobs)")
body = "\n".join(lines)

# ── 2. SCRIPTS ────────────────────────────────────────────────
script_dir = HERMES_HOME / "scripts"
body += section("Scripts", f"- **Total scripts:** {count_files(script_dir, '*.py') + count_files(script_dir, '*.sh')}\n" + "\n".join(f"  - {f.name}" for f in sorted(script_dir.iterdir()) if f.is_file() and f.suffix in ('.py','.sh')))

# ── 3. SKILLS (groups) ────────────────────────────────────────
skills_dir = HERMES_HOME / "skills"
skill_categories = {}
for f in sorted(skills_dir.rglob("SKILL.md")):
    cat = f.parent.parent.name if f.parent.parent != skills_dir else "uncategorized"
    if cat not in skill_categories:
        skill_categories[cat] = []
    skill_categories[cat].append(f.parent.name)
body += section("Skills", f"\n".join(f"  **{cat}** ({len(skills)}): {', '.join(sorted(skills))}" for cat, skills in sorted(skill_categories.items())))

# ── 4. POLICIES ───────────────────────────────────────────────
policy_dir = HERMES_HOME / "policies"
policies = []
for f in sorted(policy_dir.glob("*.json")):
    try:
        with open(f) as fh:
            p = json.load(fh)
        policies.append(p)
    except: pass
body += section("Policies", f"- **Total:** {len(policies)}\n" + "\n".join(f"  - {p.get('id','?')}: status={p.get('status','?')} domain={p.get('scope',{}).get('domain','none')} hits={p.get('hits',0)}" for p in policies))

# ── 5. PIPELINE PHASES ────────────────────────────────────────
body += section("Self-Improvement Pipeline", """- **Phase 0:** Preflight (meta-improver — snapshot, off-switch, hash check)
- **Phase 0.5:** Post-correction reflection hook
- **Phase 1:** Meta-improvement analysis
- **Phase 2:** Gap-finding
- **Phase 2b:** Cross-project bridge (health → corpus)
- **Phase 2c:** Near-miss analysis
- **Phase 3:** Self-regression
- **Phase 3b:** Self-detect scan
- **Phase 4:** Policy composition + conflict resolution
- **Phase 5:** Trend analysis (cross-day)
- **Phase 6:** Consolidation
- **Phase 7:** Postflight""")

# ── 6. CRON JOBS ──────────────────────────────────────────────
body += section("Cron Jobs", "")
if (HERMES_HOME / "cron/jobs.json").exists():
    with open(HERMES_HOME / "cron/jobs.json") as f:
        cron = json.load(f)
    for j in cron.get("jobs", []):
        name = j.get("name","?")[:45]
        sched = j.get("schedule",{}).get("display","?")
        status = j.get("last_status","?")
        last = (j.get("last_run_at") or "never")[:16]
        body += f"  - {name}: {sched} (last={last}, status={status})\n"

# ── 7. MEMORY ─────────────────────────────────────────────────
mem_count = sum(1 for f in (HERMES_HOME / "memories").glob("*.md"))
body += section("Memory", f"- **Files:** {mem_count} markdown files\n- **Tags in use:** (checked at runtime)")

# ── 8. ML MODEL ───────────────────────────────────────────────
model_path = HERMES_HOME / "models" / "miniLM-onnx"
body += section("ML Model", f"- **Model:** all-MiniLM-L6-v2 (384-dim embeddings)\n- **Size:** {fmt_size(model_path)}\n- **Location:** {model_path}")

# ── 9. EXTERNAL REPOS ─────────────────────────────────────────
repos = ["~/Documents/code/signalengine", "~/Documents/code/lux", "~/Documents/code/prospector"]
body += section("External Repos", "")
for r in repos:
    expanded = os.path.expanduser(r)
    if os.path.exists(expanded):
        out, _ = run(f"cd {expanded} && git rev-parse --short HEAD 2>/dev/null")
        body += f"  - {r.split('/')[-1]}: {expanded} (@ {out})\n"
    else:
        body += f"  - {r.split('/')[-1]}: NOT FOUND\n"

# ── 10. LOG FILES ─────────────────────────────────────────────
log_dir = HERMES_HOME / "logs"
body += section("Log Directories", "\n".join(f"  - {d.relative_to(log_dir)}/ ({sum(1 for f in d.rglob('*') if f.is_file())} files, {fmt_size(d)})" for d in sorted(log_dir.iterdir()) if d.is_dir()))

# ── WRITE ─────────────────────────────────────────────────────
report = f"# Hermes Estate Inventory\n\n**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n---{body}\n---\n## Summary\n\n"
summary = []
summary.append(f"**Scripts:** {count_files(script_dir, '*.py') + count_files(script_dir, '*.sh')}")
summary.append(f"**Skills:** {count_files(HERMES_HOME/'skills', 'SKILL.md')} across {len(skill_categories)} categories")
summary.append(f"**Policies:** {len(policies)} ({sum(1 for p in policies if p.get('status')=='active')} active)")
summary.append(f"**Cron jobs:** {len(cron.get('jobs',[])) if (HERMES_HOME/'cron/jobs.json').exists() else 0}")
summary.append(f"**Repos tracked:** {len(repos)}")
summary.append(f"**Pipeline phases:** 9 phases (preflight → postflight)")
report += "\n".join(f"- {s}" for s in summary)
report += "\n"

out_path = HERMES_HOME / "reports" / "estate-inventory.md"
out_path.parent.mkdir(parents=True, exist_ok=True)
with open(out_path, "w") as f:
    f.write(report)
print(f"Estate inventory written to {out_path}")
print(report)
