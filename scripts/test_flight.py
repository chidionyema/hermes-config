"""Hermetic proof of the Mission Engine (flight.py): a mission is plotted, flown
milestone-by-milestone on the propulsion lifecycle, and reaches its destination —
with the strategist stubbed and a temp DB (never touches the live estate)."""
import os, sys, tempfile, time, json

sys.path.insert(0, os.path.expanduser("~/.hermes/scripts"))
import coordinator as C
import flight as F

fails = []
def check(name, cond, detail=""):
    print(("PASS" if cond else "FAIL"), "-", name, ("" if cond else f"  >> {detail}"))
    if not cond: fails.append(name)

db = os.path.join(tempfile.mkdtemp(), "coord.db")
conn = C.connect(db)
C.init_db(conn)
F.init_missions_db(conn)

notes = []
notifier = lambda m: notes.append(m)

# A strategist stub that plots a 3-milestone course.
GOOD = json.dumps({"milestones": [
    {"title": "scaffold the service", "done_criterion": "build passes"},
    {"title": "wire the API", "done_criterion": "endpoint returns 200"},
    {"title": "ship behind a flag", "done_criterion": "flag deploys"}]})
def router_good(role, prompt, **kw): return GOOD
def router_junk(role, prompt, **kw): return "sorry I cannot do that"

def step_task(conn, mission_id):
    """The single active mission-step task for a mission's current milestone."""
    cur = next((x for x in F.milestones(conn, mission_id) if x["status"] != "done"), None)
    return C.get_task(conn, cur["task_id"]) if (cur and cur["task_id"]) else None

# ── 1. Create + plot ──────────────────────────────────────────────────────────────
mid = F.create_mission(conn, "TIE", "first paying customer", created_by="telegram:chidi")
check("created → plotting", F.get_mission(conn, mid)["status"] == "plotting")
F.fly(conn, F.get_mission(conn, mid), router_good, notifier)
check("plotted → flying", F.get_mission(conn, mid)["status"] == "flying")
check("3 milestones laid in", len(F.milestones(conn, mid)) == 3)
check("captain told: course plotted", any("Course plotted" in n for n in notes), notes)

# ── 2. First fly spawns a SILENT mission-step task ─────────────────────────────────
notes.clear()
F.fly(conn, F.get_mission(conn, mid), router_good, notifier)
t = step_task(conn, mid)
check("milestone 1 has a propulsion task", t is not None)
check("step task kind=mission-step", t and t["kind"] == "mission-step", dict(t) if t else None)
check("step task is NON-operator-facing (silent)", not C._is_operator_facing(t))
check("no captain ping for spawning a step", notes == [], notes)

# ── 3. Fly the whole course: each verified step advances one milestone ─────────────
# Per tick: fly() once marks the completed milestone done; the NEXT fly() spawns the
# next step (or, after the last, detects all-done → destination reached).
for i in (1, 2, 3):
    t = step_task(conn, mid)
    C._set(conn, t["id"], status="done", completed_at=time.time())     # propulsion verified it
    notes.clear()
    F.fly(conn, F.get_mission(conn, mid), router_good, notifier)        # director marks milestone done
    check(f"milestone {i} reached → captain told", any(f"{i}/3" in n for n in notes), notes)
    F.fly(conn, F.get_mission(conn, mid), router_good, notifier)        # spawn next step OR reach

check("final → DESTINATION REACHED", any("DESTINATION REACHED" in n for n in notes), notes)
check("mission status reached", F.get_mission(conn, mid)["status"] == "reached")
check("all milestones done", all(x["status"] == "done" for x in F.milestones(conn, mid)))

# ── 4. Telemetry renders ──────────────────────────────────────────────────────────
check("mission_board renders", "TIE" in F.mission_board(conn))
det = F.mission_detail(conn, "TIE")
check("mission_detail by name", det and "first paying customer" in det, det)
check("brief_line None when nothing active", F.brief_line(conn) is None)

# ── 5. BLOCKED + resume ───────────────────────────────────────────────────────────
notes.clear()
mid2 = F.create_mission(conn, "SignalEngine", "live money rail green")
F.fly(conn, F.get_mission(conn, mid2), router_good, notifier)   # plot
F.fly(conn, F.get_mission(conn, mid2), router_good, notifier)   # spawn step
t = step_task(conn, mid2)
C._set(conn, t["id"], status="escalated")                       # propulsion gave up (diagnosed)
notes.clear()
F.fly(conn, F.get_mission(conn, mid2), router_good, notifier)
check("escalated step → mission BLOCKED", F.get_mission(conn, mid2)["status"] == "blocked")
check("captain told it's blocked + how to resume", any("BLOCKED" in n and "resume" in n for n in notes), notes)
check("brief_line flags the block", "blocked" in (F.brief_line(conn) or ""), F.brief_line(conn))
check("resume_mission works", F.resume_mission(conn, mid2[:8]))
check("resumed → flying", F.get_mission(conn, mid2)["status"] == "flying")
check("resume reset the stuck milestone (fresh task next fly)", step_task(conn, mid2) is None)

# ── 6. Unplottable mission → blocks, doesn't spin forever ─────────────────────────
mid3 = F.create_mission(conn, "Impossible", "do the undoable")
for _ in range(F.MAX_PLOT_ATTEMPTS):
    F.fly(conn, F.get_mission(conn, mid3), router_junk, notifier)
check("unplottable mission → blocked after MAX_PLOT_ATTEMPTS",
      F.get_mission(conn, mid3)["status"] == "blocked", F.get_mission(conn, mid3)["status"])

print("\n" + ("ALL GREEN" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
