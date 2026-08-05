#!/usr/bin/env python3
"""Lightweight reflection pulse — runs every 30 minutes.

Cheap state check: only writes if something CHANGED since the last pulse.
Designed to be the eyes of the estate between full daily reflections.
- Reads coordinator DB (escalated tasks, recent completions)
- Reads policy firings count (last hour)
- Reads injection log volume
- Writes to logs/reflection/pulse-<timestamp>.md ONLY if delta detected
- Skips writes if state is identical (idempotent, zero noise)

Cost: ~50ms per run, zero LLM tokens, zero side effects beyond optional file write.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERMES = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()
PULSE_DIR = HERMES / "logs" / "reflection" / "pulses"
PULSE_DIR.mkdir(parents=True, exist_ok=True)

LAST_PULSE_HASH = HERMES / "logs" / "reflection" / ".last_pulse_hash"
COOR_DB = HERMES / "coordinator.db"
FIRINGS = HERMES / "logs" / "policy-firings.jsonl"
INJECTION = HERMES / "logs" / "injection-log.jsonl"


def _coor_snapshot() -> dict:
    """One cheap read of the coordinator DB. Returns None if DB unavailable."""
    if not COOR_DB.exists():
        return None
    try:
        conn = sqlite3.connect(str(COOR_DB), timeout=5)
        snap = {}
        for label, sql in [
            ("escalated", "SELECT COUNT(*) FROM tasks WHERE status='escalated'"),
            ("done_today", "SELECT COUNT(*) FROM tasks WHERE status='done' "
                           "AND COALESCE(completed_at, created_at) >= ?"),
            ("stuck_top", "SELECT id, title, consecutive_failures FROM tasks "
                          "WHERE status='escalated' OR consecutive_failures > 0 "
                          "ORDER BY consecutive_failures DESC LIMIT 3"),
        ]:
            try:
                if "?" in sql:
                    since = time.time() - 86400
                    snap[label] = conn.execute(sql, (since,)).fetchall()
                else:
                    snap[label] = conn.execute(sql).fetchall()
            except Exception:
                snap[label] = None
        conn.close()
        return snap
    except Exception:
        return None


def _firing_count_last_hour() -> int:
    if not FIRINGS.exists():
        return 0
    cutoff = datetime.now(timezone.utc).timestamp() - 3600
    n = 0
    try:
        for line in FIRINGS.read_text().splitlines():
            try:
                e = json.loads(line)
                ts = e.get("timestamp", "")
                if ts.endswith("Z"):
                    ts = ts[:-1] + "+00:00"
                t = datetime.fromisoformat(ts)
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                if t.timestamp() >= cutoff:
                    n += 1
            except Exception:
                continue
    except Exception:
        pass
    return n


def _injection_count_last_hour() -> int:
    if not INJECTION.exists():
        return 0
    cutoff = datetime.now(timezone.utc).timestamp() - 3600
    n = 0
    try:
        for line in INJECTION.read_text().splitlines()[-200:]:  # last 200 only — cheap
            try:
                e = json.loads(line)
                ts = e.get("timestamp", "")
                if ts.endswith("Z"):
                    ts = ts[:-1] + "+00:00"
                t = datetime.fromisoformat(ts)
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                if t.timestamp() >= cutoff:
                    n += 1
            except Exception:
                continue
    except Exception:
        pass
    return n


def main() -> int:
    snap = _coor_snapshot()
    firings_hr = _firing_count_last_hour()
    inj_hr = _injection_count_last_hour()

    payload = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "coordinator": snap,
        "firings_last_hour": firings_hr,
        "injections_last_hour": inj_hr,
    }

    # Hash-based dedupe — skip write if state is identical to last pulse
    h = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]
    prev = LAST_PULSE_HASH.read_text().strip() if LAST_PULSE_HASH.exists() else ""

    if h == prev:
        # Quiet — nothing changed. Print one-line to stdout so cron logs show "alive".
        print(f"[pulse] {payload['ts']} no-change")
        return 0

    # State changed — write a short pulse file
    fname = PULSE_DIR / f"pulse-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.md"
    # Format scalars correctly — COUNT(*) returns (n,) tuples, stuck_top returns (id,title,n).
    escalated_n = (snap.get('escalated') or [(0,)])[0][0] if snap else "?"
    done_n = (snap.get('done_today') or [(0,)])[0][0] if snap else "?"
    stuck_lines = []
    for r in (snap.get('stuck_top') or []) if snap else []:
        rid = str(r[0])[:8] if len(r) > 0 else "?"
        title = (r[1][:50] if len(r) > 1 and r[1] else "?")
        stuck_lines.append(f"  - `{rid}` {title}")

    lines = [
        f"# Otto Pulse — {payload['ts']}",
        "",
        f"- Escalated tasks: **{escalated_n}**",
        f"- Completed in last 24h: **{done_n}**",
        f"- Top stuck:",
        *stuck_lines,
        f"- Policy firings (last 1h): **{firings_hr}**",
        f"- Injections (last 1h): **{inj_hr}**",
        "",
        f"_hash: {h}_",
    ]
    fname.write_text("\n".join(lines))
    LAST_PULSE_HASH.write_text(h)
    print(f"[pulse] {payload['ts']} CHANGED → {fname.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
