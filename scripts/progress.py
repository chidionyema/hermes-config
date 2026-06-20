#!/usr/bin/env python3
"""progress.py — make self-improvement OBSERVABLE.

The estate already measures liveness and *current* autonomy, but nothing was
persisted over time, so "is it actually learning / getting better?" was
unanswerable. This module fixes exactly that: it snapshots the founder-pain
metric (autonomy ratio) + RSI-receipt count + cost on a cadence, and renders
the TREND with a plain-language verdict.

Claude-owned (scripts/, not a lane-protected path). 3.14-clean and 3.11-safe:
stdlib only. Wired into coordinator.tick() via a single guarded import+call,
mirroring gateway_crashloop_watch — so the daemon snapshots every tick (throttled).

CLI:
    python3 scripts/progress.py snapshot   # force a snapshot now (respects throttle)
    python3 scripts/progress.py snapshot --force
    python3 scripts/progress.py view [window_days]
"""
from __future__ import annotations

import glob
import json
import os
import sqlite3
import sys
import time

HERMES = os.path.expanduser("~/.hermes")
DB_PATH = os.path.join(HERMES, "coordinator.db")
PROOFS_GLOB = os.path.join(HERMES, "meta", "proofs", "*.json")

# Snapshot at most this often, so a 60s tick doesn't write 1440 rows/day.
# 3000s ≈ 50 min → ~hourly cadence, ~24 rows/day.
MIN_INTERVAL_S = 3000
# Trend "noticeable" threshold on the autonomy ratio (2 percentage points).
TREND_EPS = 0.02


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS progress_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL,
            window_s REAL,
            resolved INTEGER,
            auto_resolved INTEGER,
            escalated INTEGER,
            autonomy_ratio REAL,
            remind_to_investigate INTEGER,
            total_cost REAL,
            rsi_receipts INTEGER,
            tasks_open INTEGER
        );
        """
    )
    conn.commit()


def _rsi_receipt_count() -> int:
    return len(glob.glob(PROOFS_GLOB))


def _open_tasks(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE completed_at IS NULL AND status != 'escalated'"
        ).fetchone()
        return int(row[0]) if row else 0
    except sqlite3.Error:
        return 0


def _last_snapshot_ts(conn: sqlite3.Connection) -> float:
    row = conn.execute("SELECT MAX(ts) FROM progress_snapshots").fetchone()
    return float(row[0]) if row and row[0] is not None else 0.0


def snapshot(conn: sqlite3.Connection, window_s: float = 7 * 86400,
             force: bool = False, now: float | None = None) -> dict | None:
    """Capture the current improvement metrics into progress_snapshots.

    Throttled to MIN_INTERVAL_S so per-tick calls are cheap no-ops. Fully guarded
    by the caller (coordinator.tick wraps this in try/except) — must never raise
    into the propulsion loop. Returns the inserted row dict, or None if throttled.
    """
    ensure_table(conn)
    now = time.time() if now is None else now
    if not force and (now - _last_snapshot_ts(conn)) < MIN_INTERVAL_S:
        return None

    # autonomy_ratio lives in coordinator; import lazily to avoid an import cycle
    # (coordinator imports us inside tick(), not at module load).
    import coordinator as C
    m = C.autonomy_ratio(conn, window_s)

    row = {
        "ts": now,
        "window_s": window_s,
        "resolved": m["resolved"],
        "auto_resolved": m["auto_resolved"],
        "escalated": m["escalated"],
        "autonomy_ratio": m["autonomy_ratio"],
        "remind_to_investigate": m["remind_to_investigate"],
        "total_cost": m["total_cost"],
        "rsi_receipts": _rsi_receipt_count(),
        "tasks_open": _open_tasks(conn),
    }
    conn.execute(
        "INSERT INTO progress_snapshots"
        "(ts,window_s,resolved,auto_resolved,escalated,autonomy_ratio,"
        " remind_to_investigate,total_cost,rsi_receipts,tasks_open) "
        "VALUES (:ts,:window_s,:resolved,:auto_resolved,:escalated,:autonomy_ratio,"
        " :remind_to_investigate,:total_cost,:rsi_receipts,:tasks_open)",
        row,
    )
    conn.commit()
    return row


def _fmt_delta(delta: float, pct: bool = True) -> str:
    if pct:
        v = f"{abs(delta) * 100:.0f}pp"
    else:
        v = f"{abs(delta):g}"
    if delta > 0:
        return f"↑{v}"
    if delta < 0:
        return f"↓{v}"
    return "·"


def _verdict(d_autonomy: float, d_receipts: int) -> str:
    if d_autonomy > TREND_EPS:
        return "📈 *IMPROVING* — autonomy is trending up."
    if d_autonomy < -TREND_EPS:
        return "📉 *REGRESSING* — autonomy is trending down; worth a look."
    if d_receipts > 0:
        return "🔧 *WORKING* — autonomy steady, and it applied self-modifications this window."
    return "➡️ *STEADY* — autonomy flat, no self-modifications applied this window."


def view(conn: sqlite3.Connection, window_s: float = 30 * 86400,
         now: float | None = None) -> str:
    """Render the self-improvement TREND with a plain-language verdict.

    Compares the latest snapshot against the oldest snapshot inside `window_s`.
    Honest about thin history: with <2 points it says so rather than faking a trend.
    """
    ensure_table(conn)
    now = time.time() if now is None else now
    since = now - window_s
    rows = conn.execute(
        "SELECT * FROM progress_snapshots WHERE ts >= ? ORDER BY ts ASC", (since,)
    ).fetchall()
    # row_factory may or may not be set on the caller's conn; normalise to dicts.
    rows = [dict(r) if not isinstance(r, dict) else r for r in rows]

    out = ["📊 *Self-improvement — is it working?*"]
    if not rows:
        out.append("\n_No snapshots yet. The coordinator captures one ~hourly; "
                   "ask again after it has run a few times._")
        return "\n".join(out)

    latest = rows[-1]
    if len(rows) < 2:
        a = latest["autonomy_ratio"] * 100
        out.append(f"\n📌 *Baseline captured* — autonomy *{a:.0f}%*, "
                   f"{latest['rsi_receipts']} RSI receipt(s), "
                   f"{latest['escalated']} escalation(s).")
        out.append("_Trend needs ≥2 snapshots — check back after the next hourly tick._")
        return "\n".join(out)

    base = rows[0]
    span_h = max(1, int((latest["ts"] - base["ts"]) / 3600))
    d_aut = latest["autonomy_ratio"] - base["autonomy_ratio"]
    d_rec = latest["rsi_receipts"] - base["rsi_receipts"]
    d_esc = latest["escalated"] - base["escalated"]

    out.append(f"\n{_verdict(d_aut, d_rec)}")
    out.append(f"\n_over the last ~{span_h}h ({len(rows)} snapshots):_")
    out.append(f"  • Autonomy: *{latest['autonomy_ratio']*100:.0f}%*  "
               f"({_fmt_delta(d_aut)} from {base['autonomy_ratio']*100:.0f}%)")
    out.append(f"  • RSI self-mods applied: *{latest['rsi_receipts']}*  "
               f"({_fmt_delta(d_rec, pct=False)})")
    out.append(f"  • Escalations (need you): *{latest['escalated']}*  "
               f"({_fmt_delta(d_esc, pct=False)})")
    if latest["remind_to_investigate"]:
        out.append(f"  ⚠️ {latest['remind_to_investigate']} escalation(s) lacked a "
                   f"prior diagnosis — the 'resolution disease' is back.")
    out.append(f"  • Cost (7d window): *${latest['total_cost']:.4f}*")
    return "\n".join(out)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _cli() -> int:
    cmd = sys.argv[2] if False else (sys.argv[1] if len(sys.argv) > 1 else "view")
    conn = _connect()
    try:
        if cmd == "snapshot":
            force = "--force" in sys.argv
            r = snapshot(conn, force=force)
            print(json.dumps(r, indent=2) if r else "(throttled — no snapshot taken)")
            return 0
        if cmd == "view":
            days = 30.0
            for a in sys.argv[2:]:
                try:
                    days = float(a)
                except ValueError:
                    pass
            print(view(conn, window_s=days * 86400))
            return 0
        sys.stderr.write("usage: progress.py [snapshot [--force] | view [window_days]]\n")
        return 2
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(_cli())
