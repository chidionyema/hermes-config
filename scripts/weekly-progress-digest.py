#!/usr/bin/env python3
"""weekly-progress-digest — the visible-evidence dashboard the user asked for.

Day-to-day the system is silent (self-heals). Once a week it emits ONE Telegram-ready
message proving it is actually improving, not just running:

  • Dropped balls / escalations per source — this week vs last week (is it converging?)
  • Self-heals this week (balls Otto absorbed without bothering the user)
  • Noise suppressed (duplicate digests deduped)
  • Skills/rules patched this week (and which)
  • Open vs closed loops right now

Sources are substrate, not narration: the dispatch-log (queue/dispatch-log.jsonl), the
queue state, and git history of skills/. This is a no_agent cron; its stdout IS the
weekly message (deliver:origin).
"""
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta

HERMES = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
QDIR = os.path.join(HERMES, "queue")
DLOG = os.path.join(QDIR, "dispatch-log.jsonl")
SCRIPTS = os.path.join(HERMES, "scripts")
QUEUE_CLI = os.path.join(SCRIPTS, "hermes_queue.py")
NOW = datetime.now(timezone.utc)
WEEK = timedelta(days=7)


def _parse(ts):
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _dispatch_events():
    out = []
    if os.path.exists(DLOG):
        for line in open(DLOG):
            try:
                r = json.loads(line)
            except Exception:
                continue
            t = _parse(r.get("ts", ""))
            if t:
                r["_t"] = t
                out.append(r)
    return out


def _bucket(events, action, lo, hi):
    return Counter(e.get("source", "?") for e in events
                   if e.get("action") == action and lo <= e["_t"] < hi)


def _skills_patched():
    try:
        r = subprocess.run(
            ["git", "-C", HERMES, "log", "--since=7 days ago", "--name-only",
             "--pretty=format:", "--", "skills"],
            capture_output=True, text=True, timeout=20)
        files = {ln.split("/")[1] for ln in r.stdout.splitlines()
                 if ln.startswith("skills/") and "/" in ln[7:]}
        return sorted(files)
    except Exception:
        return []


def _open_loops():
    try:
        r = subprocess.run(["python3", QUEUE_CLI, "status"], capture_output=True,
                           text=True, timeout=20, env={**os.environ, "HERMES_HOME": HERMES})
        d = json.loads(r.stdout)
        return d.get("open_fingerprints", 0), d.get("dropped_ball_by_source", {})
    except Exception:
        return 0, {}


def _arrow(this, last):
    if this < last:
        return "↓"  # down = good
    if this > last:
        return "↑"  # up
    return "→"


def _product_autonomy():
    try:
        sys.path.insert(0, SCRIPTS)
        import coordinator as C
        conn = C.connect()
        try:
            m = C.autonomy_ratio(conn, 7 * 86400)
            return m
        finally:
            conn.close()
    except Exception:
        return {}


def _rsi_state():
    armed = os.path.isfile(os.path.join(HERMES, "meta", "OFF_SWITCH"))
    pending = 0
    pdir = os.path.join(HERMES, "meta", "pending")
    if os.path.isdir(pdir):
        pending = len([f for f in os.listdir(pdir) if f.startswith("pending_")])
    proofs = 0
    pr = os.path.join(HERMES, "meta", "proofs")
    if os.path.isdir(pr):
        proofs = len([f for f in os.listdir(pr) if f.endswith(".json")])
    return armed, pending, proofs


def _auto_closed_week():
    """Count coordinator auto_close events in the last 7d (junk/cron/quota parks)."""
    try:
        sys.path.insert(0, SCRIPTS)
        import coordinator as C
        conn = C.connect()
        try:
            since = (NOW - WEEK).timestamp()
            n = conn.execute(
                "SELECT COUNT(*) c FROM events WHERE kind='auto_close' AND created_at>=?",
                (since,),
            ).fetchone()["c"]
            return int(n or 0)
        finally:
            conn.close()
    except Exception:
        return 0


def main():
    ev = _dispatch_events()
    this_lo, last_lo = NOW - WEEK, NOW - 2 * WEEK
    esc_this = _bucket(ev, "escalate", this_lo, NOW)
    esc_last = _bucket(ev, "escalate", last_lo, this_lo)
    healed = sum(1 for e in ev if e.get("action") == "self-healed" and e["_t"] >= this_lo)
    deduped = sum(e.get("n", 1) for e in ev if e.get("action") == "deduped" and e["_t"] >= this_lo)
    skills = _skills_patched()
    open_fp, drops = _open_loops()
    m = _product_autonomy()
    armed, pending, proofs = _rsi_state()
    closed = _auto_closed_week()

    L = ["📊 *Otto weekly* — %s" % NOW.strftime("%Y-%m-%d")]
    L.append(
        "📈 Product autonomy (7d): *%s%%* · done `%s` · asks `%s`"
        % (
            int(round(float(m.get("product_autonomy_ratio", 0) or 0) * 100)),
            m.get("product_auto_resolved", 0),
            m.get("product_escalated", 0),
        )
    )
    L.append(
        "🧠 RSI: *%s* · staged `%d` · proofs `%d`"
        % ("ARMED" if armed else "DISARMED", pending, proofs)
    )
    L.append("🧹 Auto-closed (noise/quota/cron): `%d`" % closed)
    tt, tl = sum(esc_this.values()), sum(esc_last.values())
    L.append("Escalations (dispatch): %d %s (was %d last wk)" % (tt, _arrow(tt, tl), tl))
    srcs = sorted(set(esc_this) | set(esc_last),
                  key=lambda s: -(esc_this.get(s, 0) + esc_last.get(s, 0)))[:5]
    for s in srcs:
        L.append("  • %s: %d %s %d" % (s, esc_this.get(s, 0),
                                       _arrow(esc_this.get(s, 0), esc_last.get(s, 0)),
                                       esc_last.get(s, 0)))
    L.append("Self-healed (silent): %d   Noise suppressed: %d" % (healed, deduped))
    L.append("Open loops now: %d" % open_fp)
    if skills:
        L.append("Skills patched: %d (%s)" % (len(skills), ", ".join(skills[:6])))
    else:
        L.append("Skills patched: 0")
    # One human call — top product ask if any
    try:
        sys.path.insert(0, SCRIPTS)
        import coordinator as C
        conn = C.connect()
        try:
            asks = [d for d in C.decisions_view(conn) if C._is_operator_facing(d)]
            if asks:
                d = asks[-1]
                L.append(
                    "📥 One call: `%s` %s"
                    % (d["id"][:8], (d["title"] or "")[:50])
                )
            else:
                L.append("📥 One call: none — inbox clear")
        finally:
            conn.close()
    except Exception:
        pass
    if not ev:
        L.append("(no dispatch history yet — baseline week)")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.exit(main())
