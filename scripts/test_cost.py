"""Hermetic proof of the cost + seamlessness controls in coordinator.py:
risk-tiered routing (premium only for fence work), idle plumbing suppression,
the rolling-24h admission cap, and the fuel gauge. Temp DB, no live estate."""
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

def mk(title, kind, source, body=""):
    tid = C.open_task(conn, title=title, body=body, kind=kind, source=source, created_by="t")
    return C.get_task(conn, tid)

# ── 1. Risk-tiered routing: premium reserved for fence-class only ──────────────────
house = mk("failure: repo-health-check errored", "failure", "health-watchdog")
check("housekeeping failure → cheap chain", C._tier_role(house) == "coordinator", C._tier_role(house))

routine = mk("update the project README", "injected", "telegram")
check("routine project work → cheap chain", C._tier_role(routine) == "coordinator", C._tier_role(routine))

money = mk("port the PayPal refund flow", "injected", "telegram")
check("money/fence work → premium (strategist→claude)", C._tier_role(money) == "strategist", C._tier_role(money))

ident = mk("rotate the OIDC identity connector token", "injected", "telegram")
check("identity work → premium", C._tier_role(ident) == "strategist", C._tier_role(ident))

# ── 2. estate_idle: only founder work counts as not-idle ───────────────────────────
# DB currently holds 1 housekeeping failure + 3 injected (routine/money/ident).
# Injected tasks ARE operator-facing → not idle.
check("injected work present → NOT idle", C.estate_idle(conn) is False)

# Fresh DB: nothing at all → idle.
db2 = os.path.join(tempfile.mkdtemp(), "c2.db")
c2 = C.connect(db2); C.init_db(c2); F.init_missions_db(c2)
check("empty estate → idle", C.estate_idle(c2) is True)

# Only housekeeping → still idle (founder doesn't care).
C.open_task(c2, title="failure: lux dirty", body="{}", kind="failure", source="repo-health", created_by="queue")
check("housekeeping-only → idle", C.estate_idle(c2) is True)

# A mission-step task → not idle (real autopilot work).
C.open_task(c2, title="mission step", body="{}", kind="mission-step", source="mission:x", created_by="flight")
check("mission-step in flight → NOT idle", C.estate_idle(c2) is False)

# ── 3. ingest_failures suppresses plumbing when idle ───────────────────────────────
db3 = os.path.join(tempfile.mkdtemp(), "c3.db")
c3 = C.connect(db3); C.init_db(c3); F.init_missions_db(c3)
qfile = os.path.join(tempfile.mkdtemp(), "queue.json")
with open(qfile, "w") as f:
    json.dump({"fingerprints": {f"fp{i}": {"source": f"repo-health:{i}"} for i in range(5)}}, f)
_orig_q = C.QUEUE_STATE
C.QUEUE_STATE = qfile
try:
    check("idle estate → 0 plumbing admitted (spends nothing)", C.ingest_failures(c3) == 0)
    # Now add founder work → estate not idle → plumbing rides along (capped per tick).
    C.open_task(c3, title="ship pricing page", body="", kind="injected", source="telegram", created_by="t")
    n = C.ingest_failures(c3)
    check("with founder work present → plumbing admitted (capped)", 0 < n <= C.MAX_INGEST_PER_TICK, n)
finally:
    C.QUEUE_STATE = _orig_q

# ── 4. Daily admission cap bounds total spend ──────────────────────────────────────
db4 = os.path.join(tempfile.mkdtemp(), "c4.db")
c4 = C.connect(db4); C.init_db(c4); F.init_missions_db(c4)
_orig_budget = C.DAILY_TASK_BUDGET
C.DAILY_TASK_BUDGET = 2
qfile4 = os.path.join(tempfile.mkdtemp(), "q4.json")
with open(qfile4, "w") as f:
    json.dump({"fingerprints": {f"g{i}": {"source": f"repo-health:{i}"} for i in range(10)}}, f)
C.QUEUE_STATE = qfile4
try:
    # seed a founder task so estate isn't idle, then drive ingestion until capped
    C.open_task(c4, title="real work", body="", kind="injected", source="telegram", created_by="t")
    for _ in range(5):
        C.ingest_failures(c4)
    check("admissions never exceed DAILY_TASK_BUDGET", C.tasks_today(c4) <= C.DAILY_TASK_BUDGET + 1,
          C.tasks_today(c4))  # +1 for the seed founder task
    check("cap reached → further ingest is 0", C.ingest_failures(c4) == 0)
finally:
    C.QUEUE_STATE = _orig_q
    C.DAILY_TASK_BUDGET = _orig_budget

# ── 5. Fuel gauge renders in the brief ─────────────────────────────────────────────
b = C.operator_brief(conn)
check("brief shows the fuel gauge", "⛽" in b and "admitted" in b, b[-200:])
db5 = os.path.join(tempfile.mkdtemp(), "c5.db")
c5 = C.connect(db5); C.init_db(c5); F.init_missions_db(c5)
C.open_task(c5, title="failure: lux dirty", body="{}", kind="failure", source="repo-health", created_by="queue")
b2 = C.operator_brief(c5)  # housekeeping-only → parked
check("idle estate brief says it's parked/spending nothing", "parked" in b2, b2[-200:])

# ── 6. Heartbeat + health view (liveness observability) ────────────────────────────
db6 = os.path.join(tempfile.mkdtemp(), "c6.db")
c6 = C.connect(db6); C.init_db(c6); F.init_missions_db(c6)
check("no heartbeat before first tick", C.get_meta(c6, "last_tick") is None)
C.heartbeat(c6, "advanced=2 reaped=1")
hb = C.get_meta(c6, "last_tick")
check("heartbeat round-trips (pid|summary)", hb is not None and "advanced=2" in hb["value"], hb)
check("heartbeat carries a recent timestamp", hb and (time.time() - hb["updated_at"]) < 5)

h = C.health(c6)
check("health renders the header + verdict", "Estate health" in h and ("OPERATIONAL" in h or "DEGRADED" in h), h[:80])
check("health reports daemon liveness from heartbeat", "Coordinator daemon" in h and "ticked" in h, h)
check("health reports gateway + cron + autonomy", all(s in h for s in ("Gateway", "Cron", "Autonomy")), h)
# Stale heartbeat → daemon flagged (simulate by hand-writing an old timestamp)
c6.execute("UPDATE meta SET updated_at=? WHERE key='last_tick'", (time.time() - 9999,)); c6.commit()
hstale = C.health(c6)
check("stale heartbeat → daemon line warns", "stalled" in hstale or "⚠️" in hstale, hstale)

print("\n" + ("ALL GREEN" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
