#!/usr/bin/env python3
"""Otto Daily Self-Reflection. Runs at 6pm daily via cron.

Turns real estate telemetry into a written reflection + concrete improvement items.
Grounded in the coordinator DB (tasks/events/telemetry) — the actual source of truth —
plus gap-finding reports. All work happens in generate_reflection(); importing this module
has NO side effects (the old version generated the file on import, which was a bug)."""
import json
import os
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

REFLECTION_DIR = Path.home() / ".hermes" / "logs" / "reflection"
MAINTENANCE_LOG_DIR = Path.home() / ".hermes" / "logs" / "maintenance"
INJECTION_LOG = Path.home() / ".hermes" / "logs" / "injection-log.jsonl"
OBJECTIVES_FILE = Path.home() / "Documents" / "code" / ".hermes" / "OBJECTIVES.md"
SCRIPTS_DIR = Path.home() / ".hermes" / "scripts"


def run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() or r.stderr.strip() or "(no output)"
    except Exception as e:
        return "(error: {})".format(e)


def read_latest_gap_finding() -> list:
    """Most recent gap-finding report, near-miss, and health data → improvement items."""
    items = []
    files = sorted(MAINTENANCE_LOG_DIR.glob("gap-finding-*.json"))
    if files:
        try:
            data = json.loads(files[-1].read_text())
            for item in data.get("uncovered_domains", []):
                items.append("Create policy for uncovered domain: {}".format(item.get("domain", "?")))
            for item in data.get("weak_coverage", []):
                items.append("Tighten policy for weak domain: {} ({} failures)".format(
                    item.get("domain", "?"), item.get("failure_count", 0)))
        except (json.JSONDecodeError, OSError):
            pass
    near_miss_files = sorted(MAINTENANCE_LOG_DIR.glob("near-miss-*.json"))
    if near_miss_files:
        try:
            data = json.loads(near_miss_files[-1].read_text())
            for p in data.get("untriggered_policies", [])[:3]:
                items.append("Address untriggered policy {} ({})".format(
                    p.get("policy_id", "?"), p.get("domain", "?")))
        except (json.JSONDecodeError, OSError):
            pass
    health_log = Path.home() / ".hermes" / "logs" / "health" / "repo-health.jsonl"
    if health_log.exists():
        try:
            lines = health_log.read_text().splitlines()
            if lines:
                last = json.loads(lines[-1].strip())
                for name, result in last.get("results", {}).items():
                    if result.get("state") in ("fail", "dirty"):
                        items.append("Fix {}: {}".format(name, (result.get("summary", "issue"))[:60]))
        except (json.JSONDecodeError, OSError):
            pass
    return items[:5]


def coordinator_telemetry(window_s: float = 86400):
    """Real estate activity from the coordinator DB. Returns (data, error). Each query runs
    in its OWN try/except so a missing table/column (e.g. the live DB has no `telemetry` table)
    degrades that one field to None instead of nuking the whole section. The legacy task-queue
    JSON is a separate, largely-unused system and is deliberately ignored."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import coordinator as C
    except Exception as e:
        return None, "Coordinator module unavailable ({}).".format(e)
    try:
        conn = C.connect()
    except Exception as e:
        return None, "Coordinator DB unavailable ({}).".format(e)
    since = time.time() - window_s
    data = {}

    def q(key, sql, params=()):
        try:
            data[key] = conn.execute(sql, params).fetchall()
        except Exception:
            data[key] = None

    # Standing state across ALL tasks — escalated/stuck tasks persist beyond 24h and are the
    # point of a reflection, so status is not windowed; completions ARE windowed (recent work).
    q("by_status", "SELECT status, COUNT(*) FROM tasks GROUP BY status")
    q("stuck",
      "SELECT id, title, consecutive_failures, last_failure_error FROM tasks "
      "WHERE status='escalated' OR consecutive_failures > 0 "
      "ORDER BY consecutive_failures DESC, created_at DESC LIMIT 6")
    q("awaiting",
      "SELECT id, title, risk_class FROM tasks WHERE status='awaiting_approval' "
      "ORDER BY created_at DESC LIMIT 6")
    q("done_today",
      "SELECT COUNT(*) FROM tasks WHERE status='done' AND COALESCE(completed_at, created_at) >= ?",
      (since,))
    q("cost",  # telemetry table may not exist on older DBs — q() swallows that to None
      "SELECT COALESCE(SUM(cost),0), COALESCE(SUM(tokens_output),0) FROM telemetry "
      "WHERE timestamp >= ?", (int(since),))
    conn.close()
    return data, None


def format_telemetry():
    """Markdown for the real-activity section, and the actionable items it surfaces."""
    data, err = coordinator_telemetry()
    if err:
        return err, []
    lines, items = [], []

    bs = dict(data.get("by_status") or [])
    if bs:
        lines.append("Task ledger: " + ", ".join("{} {}".format(n, s) for s, n in sorted(bs.items())))
    else:
        lines.append("No coordinator tasks on record (estate parked or idle).")

    done_today = data.get("done_today")
    if done_today:
        lines.append("Completed in last 24h: {}".format(done_today[0][0]))

    stuck = data.get("stuck") or []
    if stuck:
        lines.append("\n**Stuck — escalated/failing (needs attention):**")
        for tid, title, cf, ferr in stuck:
            e = (ferr or "").strip().splitlines()[0][:80] if ferr else ""
            lines.append("- ⚠️ `{}` {}{}{}".format(
                str(tid)[:8], (title or "?")[:50],
                " — {}× fail".format(cf) if cf else "", " — " + e if e else ""))
            items.append("Unstick escalated task `{}`: {}".format(str(tid)[:8], (title or "?")[:50]))

    for tid, title, rc in (data.get("awaiting") or []):
        lines.append("- ⏸️ `{}` {} ({}) — awaiting your approval".format(
            str(tid)[:8], (title or "?")[:50], rc or "?"))
        items.append("Decide on fenced task `{}` ({})".format(str(tid)[:8], rc or "?"))

    cost = data.get("cost")
    if cost and cost[0] and (cost[0][0] or cost[0][1]):
        lines.append("Spend (24h): ${:.4f}, {} output tokens".format(cost[0][0] or 0, cost[0][1] or 0))
    return "\n".join(lines), items


def check_stale():
    """Orphaned ESTATE processes only (coordinator/gateway/rsi/executor). Deliberately does
    NOT match bare `claude` — the operator's own interactive sessions are legitimate and were
    false-positived as 'stale' by the previous version."""
    procs = run("ps aux | grep -E 'coordinator\\.py|rsi-orchestrator|hermes-agent|hermes .*gateway' "
                "| grep -v grep", timeout=10)
    lines = [l for l in procs.split("\n") if l.strip() and l != "(no output)"]
    if len(lines) <= 2:  # ~1 coordinator daemon + 1 gateway is nominal
        return "Estate processes nominal ({} long-lived daemon(s)).".format(len(lines))
    return "{} estate processes — check for duplicate daemons:\n```\n{}\n```".format(
        len(lines), procs[:1500])


def check_injection():
    if not INJECTION_LOG.exists():
        return "No injection log yet (Phase 2 not active)."
    today_str = str(date.today())
    try:
        entries = [json.loads(l) for l in INJECTION_LOG.read_text().splitlines() if l.strip()]
    except (json.JSONDecodeError, OSError):
        return "Could not read injection log."
    today_entries = [e for e in entries if e.get("timestamp", "").startswith(today_str)]
    if not today_entries:
        return "No strategist calls today."
    fallbacks = [e for e in today_entries if e.get("fallback_used")]
    total_chars = sum(e.get("retrieved_total_chars", 0) for e in today_entries)
    tail = ("{} fallback(s) — self-query keywords may need updating".format(len(fallbacks))
            if fallbacks else "No anomalies.")
    return "{} strategist calls, ~{} chars injected\n{}".format(len(today_entries), total_chars, tail)


def read_objectives():
    if not OBJECTIVES_FILE.exists():
        return "No objectives file yet."
    content = OBJECTIVES_FILE.read_text()
    if "## Active Objectives" in content:
        return content.split("## Active Objectives")[1].split("##")[0].strip()[:1000]
    return content[:1000]


TEMPLATE = """# Otto Daily Reflection — {today}

**Generated:** {now}

---

## 1. Estate Activity (24h, from coordinator)

{telemetry}

**Self-audit:** Did any task fail or escalate without me retrying/replanning?

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

## 5. Strategist Call Health

{injection}

---

## 6. Current State

Memory: {memory} entries

Objectives snapshot:
{objectives}

---

## 7. Improvement Plan for Tomorrow

{plan}
"""


def generate_reflection() -> Path:
    """Build today's reflection from live telemetry and write it. Returns the path."""
    REFLECTION_DIR.mkdir(parents=True, exist_ok=True)
    today_str = str(date.today())
    out_file = REFLECTION_DIR / "{}.md".format(today_str)

    telemetry_md, telemetry_items = format_telemetry()
    mem_count = run("ls ~/.hermes/memory/*.md ~/.hermes/memory/*.json 2>/dev/null | wc -l", timeout=5)

    # Improvement plan = actionable items from live telemetry first (failing/fenced tasks),
    # then gap-finding. Fall back to a sensible default if both are empty.
    plan_items = list(telemetry_items) + read_latest_gap_finding()
    if not plan_items:
        plan_items = ["No issues surfaced — review the strategist audit for structural ideas."]
    plan = "\n".join("{}. {}".format(i + 1, it) for i, it in enumerate(plan_items[:6]))

    content = TEMPLATE.format(
        today=today_str,
        now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        telemetry=telemetry_md,
        stale=check_stale(),
        injection=check_injection(),
        memory=mem_count,
        objectives=read_objectives(),
        plan=plan,
    )
    out_file.write_text(content)
    return out_file


def main() -> int:
    try:
        path = generate_reflection()
    except Exception as e:
        print("Reflection failed: {}".format(e), file=sys.stderr)
        return 1
    print("Reflection written to {}".format(path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
