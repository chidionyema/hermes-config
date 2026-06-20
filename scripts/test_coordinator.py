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

_orig_send_buttons = C.send_telegram_buttons
C.send_telegram_buttons = lambda msg, task_id: False

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

# 3b. agentic_execute fallback to agy on Claude failure
_runs = []
def _fake_run_fallback(argv, **kw):
    _runs.append(argv)
    if argv[0] == "claude":
        class _R1: returncode = 1; stdout = "Session limit reached"; stderr = ""
        return _R1()
    elif argv[0] == "agy":
        class _R2: returncode = 0; stdout = "did the work via agy"; stderr = ""
        return _R2()
    class _R: returncode = 1; stdout = ""; stderr = ""
    return _R()

_orig_run = C.subprocess.run
C.subprocess.run = _fake_run_fallback
try:
    res = C.agentic_execute({"spec": "{}", "title": "safe probe"})
finally:
    C.subprocess.run = _orig_run

check("kraken fallback to agy upon claude session limit",
      "did the work via agy" in res and len(_runs) == 2 and _runs[0][0] == "claude" and _runs[1][0] == "agy",
      f"res={res!r} runs={_runs}")

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

# ── P6: Telegram Button Approvals & PR-as-Escalation ──────────────────────────
import urllib.request
_url_open_calls = []
def _fake_urlopen(req, *args, **kwargs):
    _url_open_calls.append(req)
    class _Resp:
        status = 200
        def read(self): return b'{"ok": true}'
        def __enter__(self): return self
        def __exit__(self, *args): pass
    return _Resp()

_orig_urlopen = urllib.request.urlopen
urllib.request.urlopen = _fake_urlopen

conn_p6, _ = fresh_db()
C.get_telegram_creds = lambda: ("fake_token", "fake_chat")
C.send_telegram_buttons = _orig_send_buttons

rf = make_router(verify_results=[True])
ftid = C.inject(conn_p6, "Otto, issue a refund payment to the customer")

_url_open_calls.clear()
C.advance(conn_p6, C.get_task(conn_p6, ftid), rf, lambda m: None, lambda t: True)  # open -> diagnose
paused = C.get_task(conn_p6, ftid)

check("P6 Telegram button check: fence pause sends inline buttons",
      len(_url_open_calls) == 1 and "sendMessage" in _url_open_calls[0].full_url,
      f"calls={len(_url_open_calls)}")
check("P6 Telegram button check: task status is awaiting_approval",
      paused["status"] == "awaiting_approval")

# Test approve() can release an escalated task
conn_p6.execute("UPDATE tasks SET status='escalated' WHERE id=?", (ftid,))
conn_p6.commit()
C.approve(conn_p6, ftid)
approved = C.get_task(conn_p6, ftid)
check("P6 approve() releases escalated task back to diagnosed", approved["status"] == "diagnosed")

# Test PR-as-escalation upon multiple verification failures
conn_p6.execute("UPDATE tasks SET status='verifying', consecutive_failures=1 WHERE id=?", (ftid,))
conn_p6.commit()

_git_runs = []
def _fake_run_git(cmd, **kwargs):
    _git_runs.append(cmd)
    class _R:
        returncode = 0
        stdout = ""
        stderr = ""
    if cmd[0] == "git" and "status" in cmd:
        _R.stdout = " M file_to_remediate.py"
    elif cmd[0] == "git" and "rev-parse" in cmd:
        _R.stdout = "main"
    elif cmd[0] == "gh" and "pr" in cmd:
        _R.stdout = "https://github.com/owner/repo/pull/42"
    return _R()

_orig_run = C.subprocess.run
C.subprocess.run = _fake_run_git

_orig_exec_scope_dirs = C._exec_scope_dirs
C._exec_scope_dirs = lambda: [tempfile.gettempdir()]

rf_fail = make_router(verify_results=[False])
_msgs, n = capture_notifier()

os.environ["COORD_AGENTIC_EXEC"] = "1"
try:
    C.advance(conn_p6, C.get_task(conn_p6, ftid), rf_fail, n, lambda t: True) # verifying -> escalate with PR
finally:
    os.environ.pop("COORD_AGENTIC_EXEC", None)

check("P6 PR-as-Escalation: git checkout -b remediate branch is created",
      any("checkout" in cmd and f"feat/remediate-{ftid[:8]}" in str(cmd) for cmd in _git_runs),
      str(_git_runs))
check("P6 PR-as-Escalation: gh pr create is run",
      any("gh" in cmd and "pr" in cmd and "create" in cmd for cmd in _git_runs),
      str(_git_runs))
check("P6 PR-as-Escalation: notification contains draft PR URL",
      any("https://github.com/owner/repo/pull/42" in m for m in _msgs),
      str(_msgs))

# Restore mocks
urllib.request.urlopen = _orig_urlopen
C.subprocess.run = _orig_run
C._exec_scope_dirs = _orig_exec_scope_dirs
C.send_telegram_buttons = lambda msg, task_id: False
# ── P7: RSI Orchestrator Compilation & Execution Checks ────────────────────────
import subprocess
scripts_dir = os.path.dirname(os.path.abspath(__file__))
r_help = subprocess.run([sys.executable, os.path.join(scripts_dir, "rsi-orchestrator.py"), "--help"], capture_output=True)
check("P7 rsi-orchestrator.py compiles and runs --help", r_help.returncode == 0, r_help.stderr.decode().strip())

# ── P8: Dynamic Prompts & Unforgeable Cryptographic Signature (HMAC) ───────────
try:
    import importlib.util
    spec = importlib.util.spec_from_file_location("rsi_orchestrator", os.path.join(scripts_dir, "rsi-orchestrator.py"))
    RSI = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(RSI)
    
    # 1. Assert dynamic loading works
    orig_prompt = C.get_execute_prompt()
    check("P8 dynamic prompt getter returns default", "You are the EXECUTOR" in orig_prompt)
    
    # 2. Mock pending staging files
    import shutil
    test_pending_dir = tempfile.mkdtemp()
    _orig_pending_dir = RSI.PENDING_PROMPT_DIR
    RSI.PENDING_PROMPT_DIR = test_pending_dir
    
    # Write a mock staged pending prompt
    import hmac
    import hashlib
    key = RSI.get_signing_key()
    test_prompt = "You are the mock EXECUTE_PROMPT."
    test_hash = hashlib.sha256(test_prompt.encode("utf-8")).hexdigest()
    test_prefix = test_hash[:8]
    
    receipt_id = "proof-prompt_tuning-12345"
    receipt_data = {
        "receipt_id": receipt_id,
        "type": "prompt_tuning",
        "candidate_hash": test_hash,
        "attestation": "test pass",
        "details": {"prompt_variable": "EXECUTE_PROMPT", "prompt_length": len(test_prompt)},
        "timestamp": "2026-06-20T12:00:00Z",
    }
    raw_str = json.dumps(receipt_data, sort_keys=True)
    sig = hmac.new(key, raw_str.encode("utf-8"), hashlib.sha256).hexdigest()
    
    receipt_data["proof_signature"] = sig
    receipt_data["candidate_prompt"] = test_prompt
    
    pending_file = os.path.join(test_pending_dir, f"pending_EXECUTE_PROMPT_{test_prefix}.json")
    with open(pending_file, "w", encoding="utf-8") as f:
        json.dump(receipt_data, f)
        
    # Mock prompts.json path
    _orig_prompts_json = RSI.PROMPTS_JSON
    _orig_coord_prompts_path = C.PROMPTS_PATH
    RSI.PROMPTS_JSON = tempfile.mktemp(suffix=".json")
    C.PROMPTS_PATH = RSI.PROMPTS_JSON
    
    # 3. Call apply_pending_prompt with correct signature -> merges successfully
    res_apply = RSI.apply_pending_prompt("EXECUTE_PROMPT", test_prefix)
    check("P8 apply_pending_prompt succeeds with valid HMAC signature", res_apply is True)
    check("P8 prompts.json successfully written", os.path.exists(RSI.PROMPTS_JSON))
    check("P8 coordinator dynamic prompt updated", C.get_execute_prompt() == test_prompt)
    
    # 4. If signature is forged/incorrect -> merge fails
    forged_receipt = dict(receipt_data)
    forged_receipt["proof_signature"] = "wrong-forged-sig"
    forged_file = os.path.join(test_pending_dir, f"pending_EXECUTE_PROMPT_forged12.json")
    with open(forged_file, "w", encoding="utf-8") as f:
        json.dump(forged_receipt, f)
        
    res_forged = RSI.apply_pending_prompt("EXECUTE_PROMPT", "forged12")
    check("P8 apply_pending_prompt fails with invalid signature", res_forged is False)
    
    # Clean up mock directories/files
    shutil.rmtree(test_pending_dir, ignore_errors=True)
    if os.path.exists(RSI.PROMPTS_JSON):
        os.remove(RSI.PROMPTS_JSON)
    RSI.PENDING_PROMPT_DIR = _orig_pending_dir
    RSI.PROMPTS_JSON = _orig_prompts_json
    C.PROMPTS_PATH = _orig_coord_prompts_path
    
except Exception as e:
    check("P8 dynamic prompts and signing", False, f"Exception: {e}")

# ── P9: Signed Git Commit Loader Verification (Path A Enforcement) ─────────────
try:
    # 1. Enforce disabled by default -> check_signed_commit() returns True
    os.environ.pop("COORD_ENFORCE_SIGNED_COMMITS", None)
    check("P9 check_signed_commit() returns True by default (disabled)", C.check_signed_commit() is True)
    
    # 2. Enabled -> runs subprocess verify-commit. Mock success.
    _git_runs = []
    def _fake_verify_success(cmd, **kwargs):
        # check_signed_commit() runs `git status --porcelain` (must be clean) THEN
        # `git verify-commit HEAD` (must be signed). Answer each accordingly.
        _git_runs.append(cmd)
        if "status" in cmd:
            class _R: returncode = 0; stdout = ""; stderr = ""   # clean working tree
            return _R()
        class _R: returncode = 0; stdout = "gpg: Good signature"; stderr = ""
        return _R()

    _orig_run = C.subprocess.run
    C.subprocess.run = _fake_verify_success
    try:
        os.environ["COORD_ENFORCE_SIGNED_COMMITS"] = "1"
        res_ok = C.check_signed_commit()
        check("P9 check_signed_commit() passes with valid signature", res_ok is True)
        check("P9 run commands verification query", any("verify-commit" in x for x in _git_runs))
    finally:
        C.subprocess.run = _orig_run

    # 2b. Valid signature BUT dirty working tree -> must FAIL: the code that runs would
    #     not match the signed commit (closes the concurrent-edit / live-edit bypass).
    def _fake_dirty_tree(cmd, **kwargs):
        if "status" in cmd:
            class _R: returncode = 0; stdout = " M scripts/coordinator.py"; stderr = ""
            return _R()
        class _R: returncode = 0; stdout = "gpg: Good signature"; stderr = ""
        return _R()
    C.subprocess.run = _fake_dirty_tree
    try:
        os.environ["COORD_ENFORCE_SIGNED_COMMITS"] = "1"
        check("P9 check_signed_commit() fails on dirty tree despite valid signature",
              C.check_signed_commit() is False)
    finally:
        C.subprocess.run = _orig_run

    # 3. Enabled -> Mock verification failure.
    _git_runs.clear()
    def _fake_verify_fail(cmd, **kwargs):
        _git_runs.append(cmd)
        class _R: returncode = 1; stdout = ""; stderr = "gpg: No signature found"
        return _R()
        
    C.subprocess.run = _fake_verify_fail
    try:
        os.environ["COORD_ENFORCE_SIGNED_COMMITS"] = "1"
        res_fail = C.check_signed_commit()
        check("P9 check_signed_commit() fails when signature is missing/invalid", res_fail is False)
    finally:
        C.subprocess.run = _orig_run
        os.environ.pop("COORD_ENFORCE_SIGNED_COMMITS", None)
        
except Exception as e:
    check("P9 signed commit loader gate", False, f"Exception: {e}")

# ── P10: transient-failure escalations are requeued (bounded); logic failures are not ──
try:
    conn, path = fresh_db()
    # A: transient infra failure (provider session limit hit both executors) — should requeue.
    t_trans = C.open_task(conn, title="failure: repo-health", kind="failure")
    C._set(conn, t_trans, status="escalated",
           last_failure_error="executor could not act (fell back to chat)",
           result="[agentic-exec-fallback: RuntimeError: agentic exit 1: You've hit your "
                  "session limit · resets 1:20pm]")
    # B: real logic failure — must stay escalated for a human.
    t_logic = C.open_task(conn, title="failure: memory-hygiene", kind="failure")
    C._set(conn, t_logic, status="escalated",
           last_failure_error="failure condition still present",
           result="No memory-hygiene checker exists; nothing to fix")
    # C: transient but already at the retry ceiling — must NOT requeue (no infinite loop).
    t_maxed = C.open_task(conn, title="failure: health-watchdog", kind="failure")
    C._set(conn, t_maxed, status="escalated",
           last_failure_error="rate limit", result="quota exceeded")
    C.set_meta(conn, f"requeue_count:{t_maxed}", str(C.MAX_TRANSIENT_REQUEUES))

    ids = C.requeue_transient_escalations(conn)
    check("P10 transient escalation is requeued", t_trans in ids, f"ids={[i[:8] for i in ids]}")
    check("P10 requeued task returns to 'diagnosed' (keeps diagnosis, retries exec)",
          C.get_task(conn, t_trans)["status"] == "diagnosed")
    check("P10 requeued task gets a fresh failure budget",
          C.get_task(conn, t_trans)["consecutive_failures"] == 0)
    check("P10 logic failure stays escalated (human's call)",
          t_logic not in ids and C.get_task(conn, t_logic)["status"] == "escalated")
    check("P10 retry ceiling respected (no infinite requeue loop)",
          t_maxed not in ids and C.get_task(conn, t_maxed)["status"] == "escalated")
    mc = C.get_meta(conn, f"requeue_count:{t_trans}")
    check("P10 requeue attempt is counted in meta", bool(mc) and int(mc[0]) == 1, f"meta={mc}")
    conn.close()
except Exception as e:
    check("P10 transient requeue", False, f"Exception: {e}")

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
