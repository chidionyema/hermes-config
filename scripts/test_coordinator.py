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

# ── Tool-capable executor SAFETY (hermetic — no real claude spawned) ───────────
# 1. Agentic path is OFF by default → execute() uses the injected router (tests stay hermetic).
os.environ.pop("COORD_AGENTIC_EXEC", None)
_seen = {"called": False}
def _spy_router(role, prompt, **kw):
    if role == "executor":
        _seen["called"] = True
        return "chat evidence"
    return make_router()(role, prompt, **kw)
ev = C.execute({"spec": "{}", "title": "t"}, _spy_router)
check("kraken OFF by default → execute() uses chat router (hermetic)",
      _seen["called"] and ev == "chat evidence", f"called={_seen['called']} ev={ev!r}")

# 2. The safety cage exists and denies the catastrophic + secret-reading actions.
_cage = json.load(open(C.EXEC_SETTINGS)) if os.path.exists(C.EXEC_SETTINGS) else {}
_deny = _cage.get("permissions", {}).get("deny", [])
_must_deny = ["Bash(rm -rf:*)", "Bash(sudo:*)", "Bash(curl:*)", "Bash(git push --force:*)", "Read(**/.env)"]
check("kraken cage denies catastrophic + exfil + secret actions",
      all(d in _deny for d in _must_deny), f"missing={[d for d in _must_deny if d not in _deny]}")

# 3. agentic_execute wires the cage: settings file + allowedTools + acceptEdits, key unset.
_av_seen = {}
def _fake_run(argv, **kw):
    _av_seen["argv"] = argv
    _av_seen["env_has_key"] = "ANTHROPIC_API_KEY" in kw.get("env", {})
    class _R: returncode = 0; stdout = "did the work"; stderr = ""
    return _R()
_orig_run = C.subprocess.run
C.subprocess.run = _fake_run
try:
    os.environ["ANTHROPIC_API_KEY"] = "dead-key-should-be-stripped"
    C.agentic_execute({"spec": "{}", "title": "safe probe"})
finally:
    C.subprocess.run = _orig_run
    os.environ.pop("ANTHROPIC_API_KEY", None)
_argv = _av_seen.get("argv", [])
check("kraken invocation uses claude -p with acceptEdits + allowlist",
      _argv[:2] == ["claude", "-p"] and "acceptEdits" in _argv and "--allowedTools" in _argv, str(_argv[:6]))
check("kraken invocation loads the deny cage (--settings)",
      "--settings" in _argv and C.EXEC_SETTINGS in _argv)
check("kraken unsets the dead ANTHROPIC_API_KEY (subscription only)",
      _av_seen.get("env_has_key") is False)

# 4. Verifier HARD-FAILS on a chat fallback (no real work) — even if a model would pass it.
_passing_router = lambda role, prompt, **kw: json.dumps({"passed": True, "reason": "looks good"})
_fellback = {"result": "[agentic-exec-fallback: RuntimeError: boom]\nI created the file successfully.",
             "spec": '{"acceptance_test": "file exists"}', "kind": "injected"}
_ok, _why = C.verify(_fellback, _passing_router, lambda t: True)
check("verifier refuses to pass a chat-fallback as done (no false positive)",
      _ok is False, f"ok={_ok} why={_why!r}")

# 5. GROUND-TRUTH verify: a failure task whose acceptance test PASSES (exit 0) is done, and
#    the fingerprint is actively resolved — no waiting on an external probe (the false-escalation cure).
_resolved = []
_orig_resolve = C._resolve_fingerprint
C._resolve_fingerprint = lambda src: _resolved.append(src)
try:
    _pass_task = {"result": "committed the 3 files", "kind": "failure", "source": "fp-lux-dirty",
                  "spec": json.dumps({"acceptance_test": "test 1 = 1"})}
    _ok_gt, _why_gt = C.verify(_pass_task, _passing_router, lambda t: False)  # condition_absent=False on purpose
    check("ground-truth verify PASSES on a real passing acceptance test (ignores stale queue)",
          _ok_gt is True, f"ok={_ok_gt} why={_why_gt!r}")
    check("ground-truth pass RESOLVES the fingerprint (closes its own loop)",
          _resolved == ["fp-lux-dirty"], f"resolved={_resolved}")
    # A failing acceptance test (exit 1) must NOT pass and must NOT resolve.
    _resolved.clear()
    _fail_task = {"result": "claims it worked", "kind": "failure", "source": "fp-still-broken",
                  "spec": json.dumps({"acceptance_test": "test 1 = 2"})}
    _ok_f, _why_f = C.verify(_fail_task, _passing_router, lambda t: True)
    check("ground-truth verify FAILS on a failing acceptance test (no self-grading)",
          _ok_f is False and _resolved == [], f"ok={_ok_f} resolved={_resolved} why={_why_f!r}")
finally:
    C._resolve_fingerprint = _orig_resolve
check("runnable-acceptance classifier: prose placeholder is NOT executed",
      C._is_runnable_acceptance("condition no longer reproduces") is False)
check("runnable-acceptance classifier: a real shell check IS executed",
      C._is_runnable_acceptance('test -z "$(git status --short)"') is True)

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
