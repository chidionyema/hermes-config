#!/usr/bin/env python3
"""
daily-digest.py — 9am morning briefing.

Composes data from ops-monitor, prospector ticks, cron health, inbox, and
engine status into a Telegram-ready morning digest. Delivered via cron job
using `hermes send` to the operator's DM.
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
PROSPECTOR_TICKS = Path.home() / "Documents/code/prospector/store/scheduler/ticks.jsonl"
PROSPECTOR_PAUSE = Path.home() / "Documents/code/prospector/store/scheduler/PAUSE"
CRON_JOBS = HERMES_HOME / "cron" / "jobs.json"
COORD_DB = HERMES_HOME / "coordinator.db"


def prospector_yesterday() -> dict:
    """Prospector stats for yesterday (midnight to midnight UTC)."""
    if not PROSPECTOR_TICKS.is_file():
        return {"runs": 0, "ok": 0, "err": 0, "spent": 0.0}

    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    total = ok = err = 0
    spent = 0.0
    moat_down_minutes = 0
    last_error_ts = None

    try:
        for ln in PROSPECTOR_TICKS.read_text().splitlines():
            try:
                t = json.loads(ln)
                ts = str(t.get("ts", ""))
                if not ts.startswith(yesterday):
                    continue
                total += 1
                if t.get("error"):
                    err += 1
                    if last_error_ts is None:
                        last_error_ts = ts
                elif t.get("allowed"):
                    ok += 1
                spent = max(spent, float(t.get("today_spend_usd", 0) or 0))
            except Exception:
                continue
    except Exception:
        pass

    return {"runs": total, "ok": ok, "err": err, "spent": spent}


def prospector_now() -> dict:
    """Prospector status right now."""
    if not PROSPECTOR_TICKS.is_file():
        return {"status": "unknown", "paused": False}

    paused = PROSPECTOR_PAUSE.is_file()
    try:
        lines = PROSPECTOR_TICKS.read_text().splitlines()
        errors = 0
        for ln in lines[-5:]:
            try:
                t = json.loads(ln)
                if t.get("error"):
                    errors += 1
            except Exception:
                continue
        if errors >= 3:
            return {"status": "moat_down", "paused": paused, "consecutive_errors": errors}
        if errors > 0:
            return {"status": "degraded", "paused": paused}
        return {"status": "healthy", "paused": paused}
    except Exception:
        return {"status": "unknown", "paused": paused}


def cron_health() -> dict:
    """Cron job health summary."""
    if not CRON_JOBS.is_file():
        return {"total": 0, "failing": 0, "disabled_error": 0, "names": []}

    try:
        data = json.loads(CRON_JOBS.read_text())
        jobs = data if isinstance(data, list) else data.get("jobs", [])
        failing = []
        disabled_error = 0
        for j in jobs:
            status = j.get("last_status") or ""
            enabled = j.get("enabled", True)
            name = (j.get("name") or "?")[:40]
            if enabled and status not in (None, "", "ok"):
                failing.append(name)
            if not enabled and status not in (None, "", "ok"):
                disabled_error += 1
        return {
            "total": len(jobs),
            "failing": len(failing),
            "disabled_error": disabled_error,
            "names": failing[:4],
        }
    except Exception:
        return {"total": 0, "failing": 0, "disabled_error": 0, "names": []}


def inbox_count() -> int:
    """Number of decisions waiting."""
    import sqlite3
    if not COORD_DB.is_file():
        return 0
    try:
        conn = sqlite3.connect(str(COORD_DB), timeout=5)
        conn.row_factory = sqlite3.Row
        count = conn.execute(
            "SELECT COUNT(*) c FROM tasks WHERE status IN ('awaiting_approval','escalated')"
        ).fetchone()["c"]
        conn.close()
        return count
    except Exception:
        return 0


def engine_status() -> str:
    """Signal engine status — one word."""
    try:
        from gateway.operator_shell.signal_engine import health
        h = health()
        v = str(h.get("verdict") or "")
        if v == "ok":
            return "🟢 running"
        if v in ("tcc_denied", "down", "stalled"):
            return "🔴 stopped"
        return "🟡 degraded"
    except Exception:
        return "⚪ unknown"


def generate_digest() -> str:
    """Generate the morning digest."""
    now = datetime.now(timezone.utc)
    yesterday = prospector_yesterday()
    pnow = prospector_now()
    cron = cron_health()
    inbox = inbox_count()
    engine = engine_status()

    # Format yesterday's prospector
    yday_line = f"🔭 Prospector: {yesterday['runs']} runs"
    if yesterday['ok'] > 0 or yesterday['err'] > 0:
        yday_line += f" ({yesterday['ok']} ok, {yesterday['err']} err)"
    if yesterday['spent'] > 0:
        yday_line += f" · ${yesterday['spent']:.2f} spent"

    # Format current state
    now_parts = []
    now_parts.append(f"{engine} Engine")
    if pnow.get("paused"):
        now_parts.append("⏸ Prospector paused")
    elif pnow.get("status") == "moat_down":
        now_parts.append("🔴 Prospector moat down")
    else:
        now_parts.append("🟢 Prospector healthy")
    if cron["failing"] > 0:
        now_parts.append(f"🔴 {cron['failing']} cron failing")
    if inbox > 0:
        now_parts.append(f"📥 {inbox} decisions waiting")
    now_line = " · ".join(now_parts)

    # Top actions
    actions = []
    if pnow.get("status") == "moat_down":
        actions.append("1. 🔴 Top up Cursor/Claude credits — moat is dead")
    if cron["failing"] > 0:
        names_str = ", ".join(cron["names"][:3])
        actions.append(f"2. 🔴 Fix cron: {names_str}")
    if inbox > 0:
        actions.append(f"3. 🟡 {inbox} decisions waiting in Inbox")
    if not actions:
        actions.append("✅ Nothing urgent — estate is healthy")

    lines = [
        f"☀️ *Good morning* — {now.strftime('%a %b %d')}",
        "",
        f"*Yesterday:* {yday_line}",
        f"*Now:* {now_line}",
        "",
        "*Top actions:*",
    ] + actions

    if cron.get("disabled_error", 0) > 0:
        lines.append(f"\n_⚠️ {cron['disabled_error']} cron orphans (disabled + error) — `/cron list --all`_")

    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Daily digest")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    digest = generate_digest()
    if args.json:
        print(json.dumps({"digest": digest}))
    else:
        print(digest)


if __name__ == "__main__":
    main()
