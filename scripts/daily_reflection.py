#!/usr/bin/env python3
"""Otto Daily Self-Reflection Script. Runs at 6pm daily via cron."""
import json, os, subprocess, sys
from datetime import date, datetime
from pathlib import Path

REFLECTION_DIR = Path.home() / ".hermes" / "logs" / "reflection"
INJECTION_LOG = Path.home() / ".hermes" / "logs" / "injection-log.jsonl"
TASK_QUEUE = Path.home() / ".hermes" / "task-queue" / "jobs.json"
OBJECTIVES_FILE = Path.home() / "Documents" / "code" / ".hermes" / "OBJECTIVES.md"

today = date.today()
today_str = str(today)
reflection_file = REFLECTION_DIR / "{}.md".format(today_str)
REFLECTION_DIR.mkdir(parents=True, exist_ok=True)


def section(title, body):
    return "## {}\n\n{}\n\n".format(title, body)


def run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() or r.stderr.strip() or "(no output)"
    except Exception as e:
        return "(error: {})".format(e)


def check_stale():
    procs = run("ps aux | grep -E 'pytest|claude' | grep -v grep", timeout=10)
    lines = [l for l in procs.split("\n") if l.strip()]
    if len(lines) <= 2:
        return "No orphaned processes detected."
    return "{} processes running:\n```\n{}\n```".format(len(lines), procs[:2000])


def check_injection():
    if not INJECTION_LOG.exists():
        return "No injection log yet (Phase 2 not active)."
    with open(INJECTION_LOG) as f:
        entries = [json.loads(l) for l in f if l.strip()]
    today_entries = [e for e in entries if e.get("timestamp", "").startswith(today_str)]
    if not today_entries:
        return "No strategist calls today."
    fallbacks = [e for e in today_entries if e.get("fallback_used")]
    total_chars = sum(e.get("retrieved_total_chars", 0) for e in today_entries)
    issues = []
    if fallbacks:
        issues.append("{} fallback(s) — self-query keywords may need updating".format(len(fallbacks)))
    return "{} strategist calls, ~{} chars injected\n".format(len(today_entries), total_chars) + ("\n".join(issues) if issues else "No anomalies.")


def check_queue():
    if not TASK_QUEUE.exists():
        return "No task queue yet."
    try:
        with open(TASK_QUEUE) as f:
            jobs = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return "Could not read task queue."
    if not jobs:
        return "No queued tasks."
    running = sum(1 for j in jobs if j.get("status") == "running")
    failed = sum(1 for j in jobs if j.get("status") == "failed")
    parts = []
    if running:
        parts.append("{} running".format(running))
    if failed:
        parts.append("{} failed".format(failed))
    if not parts:
        parts.append("All complete")
    return ", ".join(parts)


def read_objectives():
    if not OBJECTIVES_FILE.exists():
        return "No objectives file yet."
    content = OBJECTIVES_FILE.read_text()
    if "## Active Objectives" in content:
        return content.split("## Active Objectives")[1].split("##")[0].strip()[:1000]
    return content[:1000]


mem_count = run("ls ~/.hermes/memory/*.json 2>/dev/null | wc -l", timeout=5)

content = """# Otto Daily Reflection — {today}

**Generated:** {now}

---

## 1. Failures Dropped

Any task that completed with non-success without recovery?
Task queue: {queue}

**Self-audit:** Did any task fail and I did not retry/replan?

---

## 2. Recurring Mistakes

Checklist:
- [ ] Killed a process without a replacement plan
- [ ] Blocked the conversation with a long synchronous task
- [ ] Failed to detect a task failure
- [ ] Waited when I should have acted

---

## 3. User Corrections

| Correction | Root cause | Fixed? |
|---|---|---|
| | | |

---

## 4. Stale Processes

{stale}

---

## 5. Where I Waited

Any point where I waited for input when I could have been acting?

---

## 6. Strategist Call Health

{injection}

---

## 7. Current State

Memory: {memory} entries

Objectives snapshot:
{objectives}

---

## 8. Improvement Plan for Tomorrow

1. 
2. 
3. 
""".format(
    today=today_str,
    now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    queue=check_queue(),
    stub="",
    stale=check_stale(),
    injection=check_injection(),
    memory=mem_count,
    objectives=read_objectives(),
)

with open(reflection_file, "w") as f:
    f.write(content)

print("Reflection written to {}".format(reflection_file))
