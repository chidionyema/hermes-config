#!/usr/bin/env python3
"""Estate diff — show ONLY what changed since last check.

Usage:
    python3 estate-diff.py              # Show diff, update snapshot
    python3 estate-diff.py --readonly   # Show diff without updating snapshot
    python3 estate-diff.py --reset      # Reset snapshot to current state (no output)

Reads the same probes as estate-audit.py but compares to a stored snapshot.
Only emits lines for things that CHANGED. Silent on success = no changes.
"""

import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SNAPSHOT = Path.home() / ".hermes" / "state" / "estate-diff-snapshot.json"
COORD_DB = Path.home() / ".hermes" / "coordinator.db"
PLIST_DIR = Path.home() / "Library" / "LaunchAgents"

DAEMONS = [
    "ai.hermes.gateway",
    "ai.hermes.coordinator",
    "ai.hermes.watchdog",
    "ai.hermes.progress",
    "ai.hermes.rsi",
]


def _uid() -> int:
    return os.getuid()


def probe_daemons() -> dict:
    """(name -> running) for estate daemons."""
    out = {}
    for label in DAEMONS:
        plist = PLIST_DIR / f"{label}.plist"
        if not plist.is_file():
            out[label] = "not_installed"
            continue
        try:
            r = subprocess.run(
                ["launchctl", "print", f"gui/{_uid()}/{label}"],
                capture_output=True, text=True, timeout=5,
            )
            stdout = r.stdout or ""
            running = "state = running" in stdout
            pid = None
            for ln in stdout.splitlines():
                if "pid =" in ln:
                    try:
                        pid = int(ln.split("=", 1)[1].strip())
                    except Exception:
                        pass
            out[label] = f"running (pid {pid})" if running and pid else "down"
        except Exception as e:
            out[label] = f"error: {e}"
    return out


def probe_tasks(conn) -> dict:
    """Count tasks by status."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT status, COUNT(*) as n FROM tasks GROUP BY status"
    ).fetchall()
    counts = {r["status"]: r["n"] for r in rows}
    escalated = conn.execute(
        "SELECT id, title, escalation_count FROM tasks WHERE status='escalated'"
    ).fetchall()
    return {
        "by_status": counts,
        "escalated": [{"id": r["id"][:8], "title": r["title"][:60],
                       "count": r["escalation_count"] or 0} for r in escalated],
    }


def probe_cron() -> dict:
    """Cron job health summary."""
    jobs_path = Path.home() / ".hermes" / "cron" / "jobs.json"
    if not jobs_path.is_file():
        return {"total": 0, "ok": 0, "failing": []}
    try:
        data = json.loads(jobs_path.read_text())
        items = data if isinstance(data, list) else data.get("jobs") or []
        ok = 0
        failing = []
        for j in items:
            if not j.get("enabled", True):
                continue
            st = j.get("last_status") or "—"
            if st == "ok":
                ok += 1
            elif st not in (None, "—"):
                failing.append({
                    "name": (j.get("name") or "?")[:40],
                    "status": st,
                    "error": str(j.get("last_error") or "")[:60],
                })
        return {"total": len([j for j in items if j.get("enabled", True)]),
                "ok": ok, "failing": failing}
    except Exception:
        return {"total": 0, "ok": 0, "failing": []}


def probe_spend() -> dict:
    """Today's spend from prospector ticks."""
    ticks = Path.home() / "Documents/code/prospector/store/scheduler/ticks.jsonl"
    if not ticks.is_file():
        return {"used": 0.0, "cap": 20.0}
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for line in reversed(ticks.read_text().strip().splitlines()):
            try:
                t = json.loads(line)
                if t.get("ts", "").startswith(today):
                    return {
                        "used": float(t.get("today_spend_usd", 0) or 0),
                        "cap": float(t.get("daily_cap_usd", 20) or 20),
                    }
            except Exception:
                continue
    except Exception:
        pass
    return {"used": 0.0, "cap": 20.0}


def probe_missions(conn) -> dict:
    """Mission summary."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT status, COUNT(*) as n FROM missions GROUP BY status"
    ).fetchall()
    return {r["status"]: r["n"] for r in rows}


def probe_all() -> dict:
    """Run all probes and return current state."""
    state = {"ts": datetime.now(timezone.utc).isoformat()}

    state["daemons"] = probe_daemons()

    try:
        conn = sqlite3.connect(str(COORD_DB), timeout=5)
        state["tasks"] = probe_tasks(conn)
        state["missions"] = probe_missions(conn)
        conn.close()
    except Exception:
        state["tasks"] = {"by_status": {}, "escalated": []}
        state["missions"] = {}

    state["cron"] = probe_cron()
    state["spend"] = probe_spend()
    return state


def _load_snapshot() -> dict | None:
    if not SNAPSHOT.is_file():
        return None
    try:
        return json.loads(SNAPSHOT.read_text())
    except Exception:
        return None


def _save_snapshot(state: dict) -> None:
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps(state, default=str, indent=2))


def _fmt_spend(used: float, cap: float) -> str:
    pct = min(used / cap, 1.0) if cap else 0
    filled = int(pct * 10)
    bar = "▓" * filled + "░" * (10 - filled)
    emoji = "🟢" if pct < 0.75 else ("🟡" if pct < 0.9 else "🔴")
    return f"{emoji} ${used:.2f} / ${cap:.2f} {bar} {pct:.0%}"


def diff(prev: dict | None, curr: dict) -> list[str]:
    """Compare current state to previous snapshot. Returns list of change lines."""
    if prev is None:
        return ["📸 *First snapshot* — run again to see changes"]

    lines = []
    prev_ts = prev.get("ts", "?")[:16].replace("T", " ")
    lines.append(f"_Since {prev_ts} UTC:_")

    # Daemons
    prev_d = prev.get("daemons", {})
    curr_d = curr.get("daemons", {})
    for name in DAEMONS:
        was = prev_d.get(name, "?")
        now = curr_d.get(name, "?")
        if was != now:
            arrow = "🔴" if "down" in str(now) else "🟢"
            lines.append(f"  {arrow} `{name.split('.')[-1]}`: {was} → {now}")

    # Tasks
    prev_t = prev.get("tasks", {}).get("by_status", {})
    curr_t = curr.get("tasks", {}).get("by_status", {})
    for status in set(list(prev_t) + list(curr_t)):
        was_n = prev_t.get(status, 0)
        now_n = curr_t.get(status, 0)
        if was_n != now_n:
            delta = now_n - was_n
            sign = "+" if delta > 0 else ""
            lines.append(f"  📋 {status}: {was_n} → {now_n} ({sign}{delta})")

    # New escalated tasks
    prev_esc = {e["id"] for e in prev.get("tasks", {}).get("escalated", [])}
    curr_esc = {e["id"] for e in curr.get("tasks", {}).get("escalated", [])}
    new_esc = curr_esc - prev_esc
    resolved_esc = prev_esc - curr_esc
    if new_esc:
        lines.append("  ⚠️ *New escalated:*")
        for e in curr.get("tasks", {}).get("escalated", []):
            if e["id"] in new_esc:
                lines.append(f"    🔴 {e['title'][:55]}")
    if resolved_esc:
        lines.append(f"  ✅ {len(resolved_esc)} escalation(s) resolved")

    # Cron
    prev_c = prev.get("cron", {})
    curr_c = curr.get("cron", {})
    prev_fail = {f["name"] for f in prev_c.get("failing", [])}
    curr_fail = {f["name"] for f in curr_c.get("failing", [])}
    if curr_fail - prev_fail:
        lines.append("  ⚠️ *New cron failures:*")
        for f in curr_c.get("failing", []):
            if f["name"] in curr_fail - prev_fail:
                lines.append(f"    🔴 {f['name']}: {f['status']}")
    if prev_fail - curr_fail:
        lines.append(f"  ✅ {len(prev_fail - curr_fail)} cron job(s) recovered")

    # Spend
    prev_s = prev.get("spend", {})
    curr_s = curr.get("spend", {})
    if prev_s.get("used", 0) != curr_s.get("used", 0):
        lines.append(f"  💰 Spend: {_fmt_spend(curr_s.get('used', 0), curr_s.get('cap', 20))}")

    # Missions
    prev_m = prev.get("missions", {})
    curr_m = curr.get("missions", {})
    for status in set(list(prev_m) + list(curr_m)):
        if prev_m.get(status) != curr_m.get(status):
            lines.append(f"  🚀 Mission {status}: {prev_m.get(status, 0)} → {curr_m.get(status, 0)}")

    if len(lines) == 1:
        return ["✅ *No changes* since last check"]

    return lines


def main():
    readonly = "--readonly" in sys.argv
    reset = "--reset" in sys.argv

    curr = probe_all()

    if reset:
        _save_snapshot(curr)
        print("Snapshot reset to current state.")
        return

    prev = _load_snapshot()
    changes = diff(prev, curr)

    if not readonly:
        _save_snapshot(curr)

    print("\n".join(changes))


if __name__ == "__main__":
    main()
