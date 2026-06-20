#!/usr/bin/env python3
"""flight.py — the MISSION ENGINE (autopilot) for the autonomous estate.

A MISSION is a DESTINATION, not a task: "TIE → first paying customer".
The flight director:
  1. PLOTS A COURSE — decomposes the destination into an ordered set of milestones
     (via the strategist), once.
  2. FLIES — on every coordinator tick it keeps exactly one milestone-step task on the
     propulsion lifecycle (coordinator open→diagnose→execute→verify). When that step
     verifies, the milestone is reached and the ship advances to the next.
  3. ARRIVES — when the last milestone is reached the destination is reached.

Signal discipline (the captain's attention is the scarce resource):
  - per-STEP work is SILENT (mission-step tasks are non-operator-facing in coordinator).
  - the captain hears ONLY: course plotted, each milestone reached, BLOCKED (needs a
    decision), destination reached. That's the whole point of an autopilot.

This module rides on coordinator.py (same DB, same lifecycle); it adds two tables
(missions, milestones) and is driven by coordinator.tick() → flight.fly_all().
"""
from __future__ import annotations

import json
import time
import uuid

import coordinator as C

MISSION_ACTIVE = ("plotting", "flying", "blocked")
MISSION_TERMINAL = ("reached", "aborted")
MAX_PLOT_ATTEMPTS = 3  # if the strategist can't produce a course in N ticks → block, don't spin

PLOT_PROMPT = (
    "You are FLIGHT DIRECTOR for an autonomous engineering estate. Decompose this MISSION "
    "into an ordered flight plan of 3-7 CONCRETE milestones that, completed in sequence, "
    "reach the destination.\n"
    "Mission: {name}\nDestination (definition of done): {goal}\nContext: {context}\n\n"
    "Return ONLY JSON: {{\"milestones\": [{{\"title\": str, \"done_criterion\": str}}]}}.\n"
    "Each done_criterion MUST be objectively checkable (a command, a file, an observable state). "
    "Order matters, earliest first. Milestones must be steps an autonomous engineering agent can "
    "ATTEMPT — not vague aspirations. No milestone may require buying services or human-only acts."
)


# ── Schema ───────────────────────────────────────────────────────────────────────
def init_missions_db(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS missions (
            id TEXT PRIMARY KEY,
            name TEXT,
            goal TEXT,              -- the destination / definition of done
            context TEXT,
            status TEXT,            -- plotting|flying|blocked|reached|aborted
            created_by TEXT,
            created_at REAL,
            reached_at REAL
        );
        CREATE TABLE IF NOT EXISTS milestones (
            id TEXT PRIMARY KEY,
            mission_id TEXT,
            seq INTEGER,
            title TEXT,
            done_criterion TEXT,
            status TEXT,            -- pending|active|done
            task_id TEXT,           -- the propulsion task currently flying this milestone
            created_at REAL,
            done_at REAL
        );
        """
    )
    conn.commit()


def _set_mission(conn, mid: str, **f) -> None:
    cols = ", ".join(f"{k}=?" for k in f)
    conn.execute(f"UPDATE missions SET {cols} WHERE id=?", (*f.values(), mid))
    conn.commit()


def _set_milestone(conn, mlid: str, **f) -> None:
    cols = ", ".join(f"{k}=?" for k in f)
    conn.execute(f"UPDATE milestones SET {cols} WHERE id=?", (*f.values(), mlid))
    conn.commit()


def _event_count(conn, mid: str, kind: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM events WHERE task_id=? AND kind=?", (mid, kind)).fetchone()[0]


# ── Read model ───────────────────────────────────────────────────────────────────
def get_mission(conn, mid: str):
    return conn.execute("SELECT * FROM missions WHERE id=?", (mid,)).fetchone()


def list_missions(conn, statuses=MISSION_ACTIVE):
    ph = ",".join("?" * len(statuses))
    return conn.execute(
        f"SELECT * FROM missions WHERE status IN ({ph}) ORDER BY created_at", statuses).fetchall()


def milestones(conn, mid: str):
    return conn.execute(
        "SELECT * FROM milestones WHERE mission_id=? ORDER BY seq", (mid,)).fetchall()


def resolve_mission(conn, ref: str):
    """Match a mission by id-prefix or (case-insensitive) name fragment, if unambiguous."""
    ref = (ref or "").strip()
    rows = conn.execute("SELECT * FROM missions WHERE id LIKE ? LIMIT 2", (ref + "%",)).fetchall()
    if len(rows) == 1:
        return rows[0]
    rows = conn.execute(
        "SELECT * FROM missions WHERE name LIKE ? COLLATE NOCASE ORDER BY created_at DESC LIMIT 2",
        ("%" + ref + "%",)).fetchall()
    return rows[0] if rows else None


# ── Course plotting ──────────────────────────────────────────────────────────────
def create_mission(conn, name: str, goal: str, created_by: str = "telegram", context: str = "") -> str:
    init_missions_db(conn)
    mid = uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO missions(id,name,goal,context,status,created_by,created_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (mid, name[:80], goal, context, "plotting", created_by, time.time()))
    conn.commit()
    C.add_event(conn, mid, "mission_created", json.dumps({"name": name, "goal": goal})[:1000])
    return mid


def plot_course(conn, mission, router=C.default_router) -> int:
    """Ask the strategist to decompose the destination into milestones. Returns count."""
    C.add_event(conn, mission["id"], "plot_attempt", "")
    try:
        txt = router("strategist", PLOT_PROMPT.format(
            name=mission["name"], goal=mission["goal"], context=mission["context"] or "(none)"))
        spec = C._extract_json(txt)
        ms = spec.get("milestones") or []
    except Exception:
        ms = []
    if not ms:
        if _event_count(conn, mission["id"], "plot_attempt") >= MAX_PLOT_ATTEMPTS:
            _set_mission(conn, mission["id"], status="blocked")
            C.add_event(conn, mission["id"], "mission_blocked", "could not plot a course")
        return 0
    for i, m in enumerate(ms):
        conn.execute(
            "INSERT INTO milestones(id,mission_id,seq,title,done_criterion,status,created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (uuid.uuid4().hex[:12], mission["id"], i,
             str(m.get("title", f"milestone {i + 1}"))[:200],
             str(m.get("done_criterion", ""))[:500], "pending", time.time()))
    conn.commit()
    _set_mission(conn, mission["id"], status="flying")
    C.add_event(conn, mission["id"], "course_plotted", json.dumps({"n": len(ms)}))
    return len(ms)


# ── The autopilot: one step per mission per tick ─────────────────────────────────
def fly(conn, mission, router=C.default_router, notifier=C.telegram_notify) -> str:
    mid = mission["id"]

    if mission["status"] == "plotting":
        n = plot_course(conn, mission, router)
        if n:
            notifier(f"🚀 Course plotted — *{mission['name']}*: {n} milestones to "
                     f"«{mission['goal'][:80]}». Flying now.")
            return "flying"
        return get_mission(conn, mid)["status"]  # may have flipped to blocked

    if mission["status"] != "flying":
        return mission["status"]

    ms = milestones(conn, mid)
    cur = next((m for m in ms if m["status"] != "done"), None)
    if cur is None:  # all milestones done → destination reached
        _set_mission(conn, mid, status="reached", reached_at=time.time())
        C.add_event(conn, mid, "mission_reached", "")
        notifier(f"🌟 *DESTINATION REACHED* — {mission['name']}: {mission['goal'][:120]}")
        return "reached"

    # Is a propulsion task already flying this milestone?
    if cur["task_id"]:
        t = C.get_task(conn, cur["task_id"])
        if t and t["status"] == "done":
            _set_milestone(conn, cur["id"], status="done", done_at=time.time())
            total = len(ms)
            notifier(f"✅ {mission['name']}: milestone {cur['seq'] + 1}/{total} reached — "
                     f"{cur['title'][:80]}")
            return "flying"
        if t and t["status"] == "escalated":
            _set_mission(conn, mid, status="blocked")
            C.add_event(conn, mid, "mission_blocked", cur["id"])
            notifier(f"🔴 *{mission['name']} BLOCKED* at milestone {cur['seq'] + 1}: "
                     f"{cur['title'][:80]}\nNeeds your call. Reply *Otto resume {mid[:8]}* "
                     f"once cleared, or *Otto abort {mid[:8]}*.")
            return "blocked"
        if t and t["status"] in C.ACTIVE:
            return "flying"  # still working this milestone — leave it

    # No live task → spawn one on the propulsion lifecycle (silent: mission-step).
    body = (f"MISSION: {mission['name']}\nDESTINATION: {mission['goal']}\n"
            f"THIS MILESTONE: {cur['title']}\nDONE WHEN: {cur['done_criterion']}\n"
            f"Context: {mission['context'] or '(none)'}")
    tid = C.open_task(conn, title=f"{mission['name']} ▸ {cur['title']}"[:120], body=body,
                      kind="mission-step", source=f"mission:{mid}", created_by="flight")
    _set_milestone(conn, cur["id"], task_id=tid, status="active")
    return "flying"


def fly_all(conn, router=C.default_router, notifier=C.telegram_notify) -> list:
    """Advance every active mission one step. Guarded so a flight error never stops the daemon."""
    try:
        init_missions_db(conn)
    except Exception:
        return []
    out = []
    for m in list_missions(conn):
        try:
            out.append(fly(conn, m, router, notifier))
        except Exception as e:
            C.add_event(conn, m["id"], "flight_error", f"{type(e).__name__}: {str(e)[:200]}")
    return out


# ── Captain commands ─────────────────────────────────────────────────────────────
def resume_mission(conn, ref: str) -> bool:
    """Un-block a mission: reset the stuck milestone and resume flying."""
    m = resolve_mission(conn, ref)
    if not m or m["status"] not in ("blocked", "flying"):
        return False
    cur = next((x for x in milestones(conn, m["id"]) if x["status"] != "done"), None)
    if cur:
        _set_milestone(conn, cur["id"], status="pending", task_id=None)
    _set_mission(conn, m["id"], status="flying")
    C.add_event(conn, m["id"], "mission_resumed", "")
    return True


def abort_mission(conn, ref: str) -> bool:
    m = resolve_mission(conn, ref)
    if not m or m["status"] in MISSION_TERMINAL:
        return False
    _set_mission(conn, m["id"], status="aborted")
    C.add_event(conn, m["id"], "mission_aborted", "")
    return True


# ── Telemetry (Telegram views) ───────────────────────────────────────────────────
def _bar(done: int, total: int, width: int = 10) -> str:
    if total <= 0:
        return "░" * width
    filled = int(round(width * done / total))
    return "▓" * filled + "░" * (width - filled)


_HEAD = {"plotting": "🧭 plotting course", "flying": "🛫 flying",
         "blocked": "🔴 BLOCKED", "reached": "🌟 reached", "aborted": "⨯ aborted"}


def mission_board(conn) -> str:
    init_missions_db(conn)
    ms = list_missions(conn, MISSION_ACTIVE + ("reached",))
    if not ms:
        return ("🛰️ No missions yet — the ship is idle.\n"
                "Set a destination: *Otto, launch <name>: <goal>*")
    out = ["🚀 *Missions*"]
    for m in ms:
        mls = milestones(conn, m["id"])
        done = sum(1 for x in mls if x["status"] == "done")
        out.append(f"\n*{m['name']}*  `{m['id'][:8]}`  — {_HEAD.get(m['status'], m['status'])}")
        out.append(f"  {_bar(done, len(mls))}  {done}/{len(mls)}")
        cur = next((x for x in mls if x["status"] != "done"), None)
        if cur and m["status"] in ("flying", "blocked"):
            out.append(f"  ▸ now: {cur['title'][:60]}")
    out.append("\n_Deep dive: «Otto mission <name>»_")
    return "\n".join(out)


def mission_detail(conn, ref: str):
    m = resolve_mission(conn, ref)
    if not m:
        return None
    mls = milestones(conn, m["id"])
    out = [f"🚀 *{m['name']}* — {_HEAD.get(m['status'], m['status'])}  `{m['id'][:8]}`",
           f"🎯 {m['goal'][:160]}", ""]
    if not mls:
        out.append("_(course not plotted yet — first tick will plan it)_")
    for x in mls:
        icon = {"done": "✅", "active": "🛫", "pending": "⬜"}.get(x["status"], "⬜")
        out.append(f"{icon} {x['seq'] + 1}. {x['title'][:70]}")
    return "\n".join(out)


def brief_line(conn) -> str | None:
    """One-line mission summary for the top of the operator brief; None if no missions."""
    init_missions_db(conn)
    act = list_missions(conn)
    if not act:
        return None
    flying = sum(1 for m in act if m["status"] == "flying")
    blocked = sum(1 for m in act if m["status"] == "blocked")
    bits = [f"{len(act)} active"]
    if flying:
        bits.append(f"{flying} flying")
    if blocked:
        bits.append(f"*{blocked} blocked*")
    return "🚀 Missions: " + ", ".join(bits)
