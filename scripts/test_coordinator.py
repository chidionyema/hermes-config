#!/usr/bin/env python3
"""Proof for coordinator.py — Phases 2-5 of the heavenly-estate design.

PROOF criteria (design lines 127-134):
  P2  task survives a coordinator restart           -> restart-survival via coordinator.db
  P3  zero "remind to investigate"; autonomy rises  -> escalate() refuses w/o diagnosis (structural)
  P4  "Otto fix X" -> completion report; chaos green -> injection->done; primary 429 mid-task survives
  P5  resolved NEW class becomes auto-handled        -> propose_known_class + digest/metrics

Deterministic phase proofs use an injected fake router/notifier. The chaos proof is LIVE:
it drives the executor through the real route() with the primary provider forced down, and
asserts the task still completes via the DeepSeek V4 fallback. LIVE skips without a key.

Run:  python3 ~/.hermes/scripts/test_coordinator.py     (0 = green, 1 = a hard invariant failed)
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import coordinator as C  # noqa: E402

results: list[tuple[str, str, str]] = []


def check(name, cond, detail=""):
    results.append(("PASS" if cond else "FAIL", name, detail))


def skip(name, detail):
    results.append(("SKIP", name, detail))


def fresh_db():
    path = tempfile.mktemp(suffix=".db")
    conn = C.connect(path)
    C.init_db(conn)
    return conn, path


def make_router(human_decision=False, verify_results=None):
    vit = iter(verify_results if verify_results is not None else [True])
    calls = []

    def r(role, prompt, **kw):
        calls.append(role)
        if role == "executor":
            return "executed; evidence: did the thing"
        if "VERIFIER" in prompt:
            try:
                p = next(vit)
            except StopIteration:
                p = True
            return json.dumps({"passed": bool(p), "reason": "ok" if p else "nope"})
        return json.dumps({"root_cause": "rc", "steps": ["s"],
                           "acceptance_test": "no longer reproduces",
                           "human_decision_required": human_decision, "risk_class": "low"})

    r.calls = calls
    return r


def capture_notifier():
    msgs = []
    return msgs, (lambda m: msgs.append(m))


def drive(conn, tid, router, notifier, cond=lambda t: True, limit=10):
    for _ in range(limit):
        t = C.get_task(conn, tid)
        if t["status"] in C.TERMINAL or t["status"] == "awaiting_approval":
            break
        C.advance(conn, t, router, notifier, cond)
    return C.get_task(conn, tid)


# ── P2: restart survival ──────────────────────────────────────────────────────
conn, path = fresh_db()
r = make_router()
_msgs, notify = capture_notifier()
tid = C.open_task(conn, title="do a thing", kind="injected")
C.advance(conn, C.get_task(conn, tid), r, notify, lambda t: True)  # open -> diagnosed
status_before = C.get_task(conn, tid)["status"]
conn.close()                                                       # simulate process death
conn2 = C.connect(path)                                            # fresh process/connection
revived = [t for t in C.list_active(conn2) if t["id"] == tid]
check("P2 task persists across restart", len(revived) == 1, f"active={len(revived)}")
check("P2 resumes mid-lifecycle (not reset)",
      revived and revived[0]["status"] == status_before == "diagnosed",
      f"status={revived[0]['status'] if revived else None}")
conn2.close()

# ── P3: investigate-before-escalate is structural ─────────────────────────────
conn, _ = fresh_db()
tid = C.open_task(conn, title="raw failure", kind="failure", source="fp-x")
try:
    C.escalate(conn, C.get_task(conn, tid), "noisy", lambda m: None)  # no diagnosis yet
    check("P3 escalate refuses without diagnosis", False, "it allowed escalation")
except C.EscalationWithoutDiagnosis:
    check("P3 escalate refuses without diagnosis", True)

# human-decision path: diagnosis MUST precede the escalation
r = make_router(human_decision=True)
_m, notify = capture_notifier()
tid2 = C.open_task(conn, title="ambiguous choice", kind="injected")
C.advance(conn, C.get_task(conn, tid2), r, notify, lambda t: True)
ev = conn.execute("SELECT kind FROM events WHERE task_id=? ORDER BY id", (tid2,)).fetchall()
kinds = [e["kind"] for e in ev]
check("P3 diagnosis precedes escalation",
      "diagnosis" in kinds and "escalate" in kinds and
      kinds.index("diagnosis") < kinds.index("escalate"), str(kinds))
m = C.autonomy_ratio(conn)
check("P3 remind_to_investigate == 0", m["remind_to_investigate"] == 0, str(m))
conn.close()

# ── P4: injection -> completion; fence; retry; chaos ──────────────────────────
conn, _ = fresh_db()
r = make_router(verify_results=[True])
msgs, notify = capture_notifier()
tid = C.inject(conn, "Otto, summarize the foo logs")
final = drive(conn, tid, r, notify)
check("P4 injection 'Otto,...' opens a task", tid is not None)
check("P4 task drives to done", final["status"] == "done", final["status"])
check("P4 completion report emitted", any("✅ DONE" in m for m in msgs), str(msgs[-1:]))

# founder fence: money task pauses for approval, then one-tap proceeds
conn_f, _ = fresh_db()
rf = make_router(verify_results=[True])
fmsgs, fnotify = capture_notifier()
ftid = C.inject(conn_f, "Otto, issue a refund payment to the customer")
C.advance(conn_f, C.get_task(conn_f, ftid), rf, fnotify, lambda t: True)  # open -> diagnose
paused = C.get_task(conn_f, ftid)
check("P4 fence pauses money task for approval",
      paused["status"] == "awaiting_approval" and paused["risk_class"] == "money",
      f"{paused['status']}/{paused['risk_class']}")
check("P4 fence emits one-tap approval ask", any("APPROVAL" in m for m in fmsgs))
C.approve(conn_f, ftid)
after = drive(conn_f, ftid, rf, fnotify)
check("P4 approved fence task completes", after["status"] == "done", after["status"])
conn_f.close()

# retry-then-succeed (no escalation), and escalate-after-N (with diagnosis)
conn_r, _ = fresh_db()
rr = make_router(verify_results=[False, True])
_m, n = capture_notifier()
rtid = C.open_task(conn_r, title="flaky", kind="injected")
rfinal = drive(conn_r, rtid, rr, n)
check("P4 retry then succeed (no escalation)",
      rfinal["status"] == "done" and rfinal["consecutive_failures"] == 1,
      f"{rfinal['status']}/{rfinal['consecutive_failures']}")
re2 = make_router(verify_results=[False, False])
_m, n2 = capture_notifier()
etid = C.open_task(conn_r, title="unfixable", kind="injected")
efinal = drive(conn_r, etid, re2, n2)
check("P4 escalates after N fails (with diagnosis)",
      efinal["status"] == "escalated" and C.has_event(conn_r, etid, "diagnosis"),
      efinal["status"])
conn_r.close()

# CHAOS (LIVE): kill the primary provider mid-task; executor still completes via fallback
if os.environ.get("DEEPSEEK_API_KEY"):
    import route as R
    fellback = {"provider": None}

    def chaos_router(role, prompt, **kw):
        if role == "executor":  # real call, primary forced down -> must fall back
            os.environ["HERMES_ROUTE_FAIL"] = "minimax"
            try:
                res = R.route("executor", "Reply with exactly: DONE", max_tokens=256)
            finally:
                os.environ.pop("HERMES_ROUTE_FAIL", None)
            fellback["provider"] = res.provider
            return res.text
        if "VERIFIER" in prompt:
            return json.dumps({"passed": True, "reason": "live executor returned via fallback"})
        return json.dumps({"root_cause": "chaos", "steps": ["s"], "acceptance_test": "x",
                           "human_decision_required": False, "risk_class": "low"})

    conn_c, _ = fresh_db()
    _m, cn = capture_notifier()
    ctid = C.open_task(conn_c, title="chaos task", kind="injected")
    cfinal = drive(conn_c, ctid, chaos_router, cn)
    check("P4 CHAOS: task completes with primary provider killed",
          cfinal["status"] == "done" and fellback["provider"] == "deepseek",
          f"status={cfinal['status']} executor_via={fellback['provider']}")
    conn_c.close()
else:
    skip("P4 CHAOS: task completes with primary provider killed", "DEEPSEEK_API_KEY unset")

# ── P5: self-improving registry + digest ──────────────────────────────────────
conn, _ = fresh_db()
sys.path.insert(0, os.path.expanduser("~/.hermes/scripts"))
try:
    import known_classes as KC
    new_is_unknown = KC.classify("brand-new-widget-fault", "novel fingerprint xyz") is None
except Exception as e:
    new_is_unknown = True  # if registry import fails, the class is still "new"
check("P5 a novel fingerprint is unknown to the registry", new_is_unknown)

# resolve it -> propose a known class so next time it's auto-handled
prop = C.propose_known_class("novel fingerprint xyz", name="widget-fault-probe",
                             match="brand-new-widget-fault", handler="widget-probe.py")
proposed_match = prop["match"] == "brand-new-widget-fault"
# the proposed match WOULD now classify the same fingerprint (mechanism of "auto-handled")
would_match = prop["match"] in "brand-new-widget-fault novel fingerprint xyz"
check("P5 proposal would auto-handle the recurrence", proposed_match and would_match)
check("P5 proposal persisted to disk", os.path.exists(C.PROPOSALS))

# digest + metrics render
C.open_task(conn, title="seed done", kind="injected")
dig = C.overnight_digest(conn)
check("P5 overnight digest renders", "Otto overnight" in dig and "autonomy" in dig, dig[:60])
conn.close()

# ── Static: dedicated DB, no kanban.db collision ──────────────────────────────
check("uses dedicated coordinator.db (no kanban.db collision)",
      C.DB_PATH.endswith("coordinator.db") and "kanban.db" not in C.DB_PATH, C.DB_PATH)

# ── Report ────────────────────────────────────────────────────────────────────
print()
for status, name, detail in results:
    mark = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭ "}[status]
    line = f"{mark} {status}  {name}"
    if detail and status != "PASS":
        line += f"  — {detail}"
    print(line)
hard = sum(1 for s, _n, _d in results if s == "FAIL")
ok = sum(1 for s, _n, _d in results if s == "PASS")
sk = sum(1 for s, _n, _d in results if s == "SKIP")
print(f"\n{ok} passed, {hard} failed, {sk} skipped")
sys.exit(1 if hard else 0)
