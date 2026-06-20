#!/usr/bin/env python3
"""coordinator.py — the persistent autonomous-estate coordinator (Phases 2-5).

Design: ~/.hermes/reports/heavenly-estate-architecture-2026-06-20.md
Roles routed via route.py (Phase 1, proven): coordinator=deepseek-v4, strategist=claude,
executor=minimax. This module is the missing persistent loop that OWNS a task lifecycle:

    open ─► diagnosed ─► executing ─► verifying ─► done
              │  └─(money/identity/contract)─► awaiting_approval ─(human one-tap)─┐
              └─(human-decision-required, WITH diagnosis attached)─► escalated     │
                       verifying ─(fail ×N, evidence attached)─► escalated         │
                                                                                   ▼
                                                                 (approve) ─► executing

WHY a dedicated coordinator.db (not kanban.db): the gateway already runs its OWN kanban
dispatcher every 60s (config kanban.dispatch_in_gateway=true). Writing our tasks into
kanban.db would let that dispatcher double-claim them. A separate DB keeps the same
"source of truth survives restart" property without fighting the gateway.

THE CURE (Phase 3, the founder's core pain): escalate() REFUSES to fire unless a
'diagnosis' event already exists for the task. "Ping the human without investigating
first" is therefore structurally impossible — investigate-before-escalate is an
invariant, not a hope.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import uuid

import route as _route

HERMES = os.path.expanduser("~/.hermes")
DB_PATH = os.path.join(HERMES, "coordinator.db")
QUEUE_STATE = os.path.join(HERMES, "queue", "state.json")
PROPOSALS = os.path.join(HERMES, "queue", "known-class-proposals.jsonl")

# Lifecycle
ACTIVE = ("open", "diagnosed", "executing", "verifying", "awaiting_approval")
TERMINAL = ("done", "escalated", "blocked")

MAX_RETRIES = 2              # verify failures before escalating WITH evidence
HEARTBEAT_STALE_S = 1800     # a task with no heartbeat this long is reaped + retried

# Founder fence — these classes auto-DIAGNOSE but PAUSE for one-tap human approval.
FENCE = {
    "money":    r"\b(payment|payout|refund|charge|invoice|billing|stripe|paypal|money|wallet|ledger|settle)\b",
    "identity": r"\b(identity|kyc|auth|credential|password|secret|token|oauth|login|account)\b",
    "contract": r"\b(contract|migration|schema\s*migration|terms|legal|tos)\b",
}


# ── DB ──────────────────────────────────────────────────────────────────────────
def connect(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            kind TEXT,              -- 'failure' | 'injected'
            source TEXT,            -- fingerprint, or 'telegram'
            title TEXT,
            body TEXT,
            risk_class TEXT,        -- low|money|identity|contract (set at diagnosis)
            status TEXT,
            spec TEXT,              -- JSON diagnosis+spec from strategist
            result TEXT,            -- executor evidence
            consecutive_failures INTEGER DEFAULT 0,
            last_failure_error TEXT,
            created_by TEXT,
            created_at REAL,
            started_at REAL,
            completed_at REAL,
            last_heartbeat_at REAL
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT,
            kind TEXT,
            payload TEXT,
            created_at REAL
        );
        """
    )
    conn.commit()


def add_event(conn, task_id: str, kind: str, payload: str = "") -> None:
    conn.execute(
        "INSERT INTO events(task_id,kind,payload,created_at) VALUES (?,?,?,?)",
        (task_id, kind, payload, time.time()),
    )
    conn.commit()


def has_event(conn, task_id: str, kind: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM events WHERE task_id=? AND kind=? LIMIT 1", (task_id, kind)
    ).fetchone()
    return row is not None


def open_task(conn, *, title: str, body: str = "", kind: str = "injected",
              source: str = "telegram", created_by: str = "telegram") -> str:
    tid = uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO tasks(id,kind,source,title,body,status,consecutive_failures,created_by,created_at)"
        " VALUES (?,?,?,?,?,?,0,?,?)",
        (tid, kind, source, title, body, "open", created_by, time.time()),
    )
    conn.commit()
    add_event(conn, tid, "opened", json.dumps({"kind": kind, "source": source}))
    return tid


def get_task(conn, task_id: str):
    return conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()


def list_active(conn):
    q = "SELECT * FROM tasks WHERE status IN (%s) ORDER BY created_at" % ",".join("?" * len(ACTIVE))
    return conn.execute(q, ACTIVE).fetchall()


def _set(conn, task_id: str, **fields) -> None:
    cols = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE tasks SET {cols} WHERE id=?", (*fields.values(), task_id))
    conn.commit()


# ── Routing helpers ──────────────────────────────────────────────────────────────
def default_router(role: str, prompt: str, **kw) -> str:
    """Send via the proven per-role fallback chain; return the text content."""
    return _route.route(role, prompt, **kw).text


def _extract_json(text: str) -> dict:
    """Pull the first {...} object out of a model reply; {} on failure."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}


def fence_class(text: str) -> str:
    low = (text or "").lower()
    for cls, pat in FENCE.items():
        if re.search(pat, low):
            return cls
    return "low"


# ── Role steps (each goes through route.py) ──────────────────────────────────────
DIAGNOSE_PROMPT = (
    "You are the STRATEGIST for an autonomous ops estate. Diagnose this task and emit a fix spec.\n"
    "Task title: {title}\nDetails: {body}\n\n"
    "Return ONLY JSON: {{\"root_cause\": str, \"steps\": [str], \"acceptance_test\": str, "
    "\"human_decision_required\": bool, \"risk_class\": \"low\"|\"money\"|\"identity\"|\"contract\"}}.\n"
    "acceptance_test MUST be a SINGLE, self-contained, READ-ONLY shell command whose exit code "
    "is the verdict (exit 0 == the failure is gone). It MUST re-derive state LIVE (e.g. "
    "`git status --short`, a `grep`, a `pgrep`, a build/test invocation) and MUST NOT read cached "
    "or asynchronously-updated health logs (repo-health.jsonl, watchdog-state.json, queue/state.json) "
    "— those lag reality and cause false failures. No network, no mutations.\n"
    "Set human_decision_required=true ONLY if a human must choose between real alternatives "
    "(not merely to be informed). Investigate first; never punt a diagnosis back to a human."
)
EXECUTE_PROMPT = (
    "You are the EXECUTOR. Carry out this spec and report what you did + evidence.\n"
    "Spec: {spec}\nTask: {title}\n\nReturn a short factual result with concrete evidence."
)
VERIFY_PROMPT = (
    "You are the VERIFIER. NO self-grading; be ADVERSARIAL and strict.\n"
    "Acceptance test: {acceptance_test}\nEvidence (the executor's ACTUAL output):\n{evidence}\n\n"
    "PASS only if the evidence contains CONCRETE PROOF the acceptance test is literally satisfied "
    "right now — real command output, file contents, or test results visible in the evidence. "
    "FAIL if the evidence is only a plan / intention / 'I will' / a description with no actual "
    "output, or if the proof is missing or ambiguous. When in doubt, FAIL.\n"
    "Return ONLY JSON: {{\"passed\": bool, \"reason\": str}}."
)


def diagnose(task, router) -> dict:
    txt = router("strategist", DIAGNOSE_PROMPT.format(title=task["title"], body=task["body"] or ""),
                 max_tokens=900)
    spec = _extract_json(txt)
    spec.setdefault("root_cause", txt.strip()[:300])
    spec.setdefault("steps", [])
    spec.setdefault("acceptance_test", "condition no longer reproduces")
    spec.setdefault("human_decision_required", False)
    # Risk is the STRICTER of model opinion and keyword fence (never downgrade).
    kw_risk = fence_class(f"{task['title']} {task['body'] or ''}")
    spec["risk_class"] = kw_risk if kw_risk != "low" else spec.get("risk_class", "low")
    return spec


def _strip_think(text: str) -> str:
    """MiniMax-M3 / reasoners leak <think>…</think> into content — keep only the answer."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


# ── Tool-capable executor — the "kraken", safely caged ───────────────────────────
# A raw chat completion can only NARRATE a fix; this runs a REAL agent (claude -p) that
# can Read/Edit/Write/Bash to actually perform it. Safety is LAYERED, never one flag:
#   1. the FENCE pauses money/identity/contract BEFORE execute() is ever called;
#   2. claude runs with EXEC_SETTINGS deny rules (no rm -rf/sudo/dd/force-push/curl, no
#      reading .env/secrets/keys) — the blast-radius limiter;
#   3. filesystem reach is pinned to explicit --add-dir roots (default: code + ~/.hermes);
#   4. acceptEdits auto-applies edits but every Bash stays deny-gated;
#   5. a hard wall-clock timeout;
#   6. the strict claude-cli VERIFIER still gates 'done' (no self-grading);
#   7. full stdout is audit-logged as the task's evidence.
# Gated behind COORD_AGENTIC_EXEC=1 so the daemon acts for real while tests stay hermetic.
EXEC_SETTINGS = os.path.join(HERMES, "executor-settings.json")
EXEC_ALLOWED_TOOLS = "Read Edit Write Grep Glob Bash"
EXEC_TIMEOUT_S = int(os.environ.get("COORD_EXEC_TIMEOUT", "600"))


def _exec_scope_dirs() -> list[str]:
    raw = os.environ.get("COORD_EXEC_DIRS",
                         f"{os.path.expanduser('~/Documents/code')}:{HERMES}")
    return [d for d in raw.split(":") if d and os.path.isdir(d)]


def agentic_execute(task) -> str:
    """Run the spec with a real, tool-capable, deny-caged agent. Raises on failure so
    execute() can fall back to chat (which fails the verifier → safe retry/escalate)."""
    prompt = EXECUTE_PROMPT.format(spec=task["spec"] or "{}", title=task["title"])
    dirs = _exec_scope_dirs()
    argv = ["claude", "-p", "--permission-mode", "acceptEdits",
            "--allowedTools", EXEC_ALLOWED_TOOLS]
    if os.path.exists(EXEC_SETTINGS):
        argv += ["--settings", EXEC_SETTINGS]
    for d in dirs:
        argv += ["--add-dir", d]
    # NB: --add-dir / --allowedTools are VARIADIC (nargs='+') — a positional prompt would
    # be swallowed as another directory. Feed the prompt on STDIN instead.
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)   # subscription/OAuth, never the dead pay-per-token key
    proc = subprocess.run(argv, input=prompt, capture_output=True, text=True,
                          timeout=EXEC_TIMEOUT_S, env=env,
                          cwd=(dirs[0] if dirs else None))
    out = (proc.stdout or "").strip()
    if proc.returncode != 0 or not out:
        raise RuntimeError(f"agentic exit {proc.returncode}: {(proc.stderr or out)[:200]}")
    return out


def execute(task, router) -> str:
    spec = task["spec"] or "{}"
    if os.environ.get("COORD_AGENTIC_EXEC") == "1":   # production: act for real
        try:
            return _strip_think(agentic_execute(task))
        except Exception as e:                        # resilience: degrade to reasoning
            chat = router("executor", EXECUTE_PROMPT.format(spec=spec, title=task["title"]),
                          max_tokens=2000)
            return _strip_think(f"[agentic-exec-fallback: {type(e).__name__}: {str(e)[:120]}]\n{chat}")
    # Reasoners need output headroom or the answer truncates (finish=length) — give room.
    return _strip_think(router("executor", EXECUTE_PROMPT.format(spec=spec, title=task["title"]),
                              max_tokens=2000))


# ── Ground-truth verification helpers ────────────────────────────────────────────
HERMES_QUEUE = os.path.join(HERMES, "scripts", "hermes_queue.py")
ACCEPT_TIMEOUT_S = int(os.environ.get("COORD_ACCEPT_TIMEOUT", "120"))
_ACCEPT_TOKENS = ("&&", "||", ";", "$(", "`", "test ", "test -", "git ", "grep ",
                  "python", "pgrep", "ls ", "cat ", "[ -", "diff ", "jq ", "make ",
                  "npm ", "pytest", "dotnet ", "go ")


def _is_runnable_acceptance(acc: str) -> bool:
    """True if the acceptance string is an executable shell check, not a prose placeholder."""
    a = (acc or "").strip()
    if not a or a.lower().startswith(("condition no longer", "n/a", "none")):
        return False
    return any(tok in a for tok in _ACCEPT_TOKENS)


def _run_acceptance(acc: str) -> tuple[bool, str]:
    """Execute the strategist's acceptance test as GROUND TRUTH — exit 0 == resolved.
    Read-only by construction (the diagnose prompt mandates it); bounded by a timeout."""
    try:
        proc = subprocess.run(["/bin/zsh", "-c", acc], capture_output=True, text=True,
                              timeout=ACCEPT_TIMEOUT_S)
        out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        return proc.returncode == 0, (out or f"(exit {proc.returncode}, no output)")[:300]
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:160]}"


def _resolve_fingerprint(source: str) -> None:
    """Probe-verified resolution: clear this fingerprint from the live queue so the failure
    stops re-firing. Closes our own loop (otto's documented post-remediation pattern) instead
    of waiting for an external probe — the wait that caused false 'still present' escalations."""
    if not source:
        return
    try:
        subprocess.run([sys.executable, HERMES_QUEUE, "resolve", "--fingerprint", source],
                       capture_output=True, text=True, timeout=30)
    except Exception:
        pass


def verify(task, router, condition_absent) -> tuple[bool, str]:
    """Done only when GROUND TRUTH confirms the failure is gone — no self-grading."""
    evidence = task["result"] or ""
    # Hard gate: if execution fell back to chat, the agent could NOT act → no real work was
    # done, no matter how confident the narration reads. Never let this be graded as passed.
    if "[agentic-exec-fallback" in evidence:
        return False, "executor could not act (fell back to chat) — no real work performed"
    spec = _extract_json(task["spec"] or "{}")
    acc = (spec.get("acceptance_test") or "").strip()
    # PRIMARY path for failure tasks: RUN the acceptance test against live state, and on pass
    # actively RESOLVE the fingerprint — closing our own loop rather than waiting for an external
    # probe to clear the queue (the wait that bounced fixed tasks into false escalations).
    if task["kind"] == "failure" and _is_runnable_acceptance(acc):
        ok, detail = _run_acceptance(acc)
        if not ok:
            return False, f"acceptance test failed (exit≠0): {detail}"
        _resolve_fingerprint(task["source"])
        return True, f"acceptance test passed (ground truth); fingerprint resolved. {detail[:140]}"
    # FALLBACK (injected tasks, or a non-runnable acceptance string): require the live failure
    # signal to be gone AND an adversarial judge to confirm the evidence.
    if not condition_absent(task):
        return False, "failure condition still present"
    txt = router("strategist", VERIFY_PROMPT.format(
        acceptance_test=acc, evidence=evidence[:1500]), max_tokens=300)
    j = _extract_json(txt)
    return bool(j.get("passed")), str(j.get("reason", txt[:200]))


def default_condition_absent(task) -> bool:
    """For failure tasks: is the fingerprint gone from the queue? Injected tasks: trivially true."""
    if task["kind"] != "failure":
        return True
    try:
        with open(QUEUE_STATE) as f:
            fps = json.load(f).get("fingerprints", {})
        return task["source"] not in fps
    except Exception:
        return True


# ── Notification ────────────────────────────────────────────────────────────────
def telegram_notify(msg: str) -> None:
    """One honest line to Telegram via the hermes CLI. Best-effort; never raises."""
    try:
        subprocess.run(["hermes", "send", "--to", "telegram", msg],
                       timeout=30, capture_output=True)
    except Exception:
        pass


# ── Escalation — THE CURE ────────────────────────────────────────────────────────
class EscalationWithoutDiagnosis(RuntimeError):
    """Refused: tried to ping the human before investigating. This must never happen."""


def escalate(conn, task, reason: str, notifier, decision: bool = False) -> None:
    if not has_event(conn, task["id"], "diagnosis"):
        raise EscalationWithoutDiagnosis(
            f"task {task['id']} has no diagnosis — investigate before escalating")
    add_event(conn, task["id"], "escalate", json.dumps({"reason": reason, "decision": decision}))
    _set(conn, task["id"], status="escalated")
    spec = _extract_json(task["spec"] or "{}")
    head = "🔵 DECISION NEEDED" if decision else "🔴 ESCALATED (diagnosed, needs human)"
    notifier(f"{head}: {task['title']}\nwhy: {reason}\nroot cause: {spec.get('root_cause','(see task)')[:200]}")


# ── State machine: advance ONE step (so a restart resumes cleanly) ───────────────
def advance(conn, task, router=default_router, notifier=telegram_notify,
            condition_absent=default_condition_absent, max_retries: int = MAX_RETRIES) -> str:
    tid = task["id"]
    _set(conn, tid, last_heartbeat_at=time.time())
    st = task["status"]

    if st == "open":
        spec = diagnose(task, router)                       # INVESTIGATE FIRST, always
        add_event(conn, tid, "diagnosis", json.dumps(spec)[:2000])
        _set(conn, tid, spec=json.dumps(spec), risk_class=spec["risk_class"])
        task = get_task(conn, tid)
        if spec.get("human_decision_required"):
            escalate(conn, task, "strategist: human decision required", notifier, decision=True)
            return "escalated"
        if spec["risk_class"] != "low":                     # founder fence
            add_event(conn, tid, "fence_pause", spec["risk_class"])
            _set(conn, tid, status="awaiting_approval")
            notifier(f"⏸️ APPROVAL ({spec['risk_class']}): {task['title']}\n"
                     f"diagnosed: {spec.get('root_cause','')[:160]}\nreply approve to execute.")
            return "awaiting_approval"
        _set(conn, tid, status="diagnosed")
        return "diagnosed"

    if st == "diagnosed":
        _set(conn, tid, status="executing", started_at=task["started_at"] or time.time())
        return "executing"

    if st == "executing":
        evidence = execute(task, router)
        add_event(conn, tid, "executed", evidence[:1000])
        _set(conn, tid, result=evidence, status="verifying")
        return "verifying"

    if st == "verifying":
        ok, reason = verify(task, router, condition_absent)
        add_event(conn, tid, "verify", json.dumps({"ok": ok, "reason": reason})[:600])
        if ok:
            _set(conn, tid, status="done", completed_at=time.time())
            notifier(f"✅ DONE: {task['title']} — {reason[:140]}")
            return "done"
        fails = task["consecutive_failures"] + 1
        _set(conn, tid, consecutive_failures=fails, last_failure_error=reason[:300])
        if fails >= max_retries:
            escalate(conn, get_task(conn, tid),
                     f"failed verification {fails}× — {reason[:160]}", notifier)
            return "escalated"
        _set(conn, tid, status="diagnosed")                 # retry: re-spec then re-execute
        return "diagnosed"

    if st == "awaiting_approval":
        return "awaiting_approval"                           # waits for approve()

    return st


def approve(conn, task_id: str) -> bool:
    """Human one-tap: release a fence-paused task into execution."""
    t = get_task(conn, task_id)
    if not t or t["status"] != "awaiting_approval":
        return False
    add_event(conn, task_id, "approved", "")
    _set(conn, task_id, status="diagnosed")
    return True


def reap_stale(conn) -> int:
    """Re-queue tasks whose worker went silent (orphan-safe: just resets status)."""
    now = time.time()
    n = 0
    for t in list_active(conn):
        hb = t["last_heartbeat_at"] or 0
        if t["status"] == "executing" and hb and (now - hb) > HEARTBEAT_STALE_S:
            add_event(conn, t["id"], "reaped", f"stale {int(now-hb)}s")
            _set(conn, t["id"], status="diagnosed",
                 consecutive_failures=t["consecutive_failures"] + 1)
            n += 1
    return n


# ── Tick + daemon loop ───────────────────────────────────────────────────────────
def tick(conn, router=default_router, notifier=telegram_notify,
         condition_absent=default_condition_absent) -> dict:
    """One coordinator pass: ingest new failures, reap stragglers, advance every task one step."""
    ingest_failures(conn)
    reaped = reap_stale(conn)
    moved = []
    for t in list_active(conn):
        try:
            moved.append(advance(conn, t, router, notifier, condition_absent))
        except EscalationWithoutDiagnosis:
            raise
        except Exception as e:  # a single task error must not stop the loop
            add_event(conn, t["id"], "error", f"{type(e).__name__}: {str(e)[:200]}")
    return {"reaped": reaped, "advanced": len(moved), "states": moved}


MAX_INGEST_PER_TICK = int(os.environ.get("COORD_MAX_INGEST", "3"))
MAX_INFLIGHT = int(os.environ.get("COORD_MAX_INFLIGHT", "6"))


def ingest_failures(conn) -> int:
    """Turn new queue fingerprints into coordinator tasks — ADMISSION-CONTROLLED so a
    backlog drains gradually instead of storming the providers on one tick.
    Caps: at most MAX_INGEST_PER_TICK new tasks/tick, and never exceed MAX_INFLIGHT active."""
    try:
        with open(QUEUE_STATE) as f:
            fps = json.load(f).get("fingerprints", {})
    except Exception:
        return 0
    existing = {r["source"] for r in conn.execute("SELECT source FROM tasks").fetchall()}
    inflight = len(list_active(conn))
    budget = min(MAX_INGEST_PER_TICK, max(0, MAX_INFLIGHT - inflight))
    n = 0
    for fp, meta in fps.items():
        if budget <= 0:
            break
        if fp in existing:
            continue
        open_task(conn, title=f"failure: {meta.get('source', fp)}",
                  body=json.dumps(meta)[:1000], kind="failure", source=fp, created_by="queue")
        n += 1
        budget -= 1
    return n


def inject(conn, text: str, created_by: str = "telegram") -> str | None:
    """Two-way Telegram: 'Otto, port the PayPal refund flow' -> a tracked task."""
    m = re.match(r"\s*otto[,:]?\s+(.*)", text, re.IGNORECASE | re.DOTALL)
    task_text = (m.group(1) if m else text).strip()
    if not task_text:
        return None
    return open_task(conn, title=task_text[:120], body=task_text,
                     kind="injected", source="telegram", created_by=created_by)


# ── Phase 5: self-improving registry + digest ────────────────────────────────────
def propose_known_class(fingerprint: str, name: str, match: str,
                        handler: str | None = None) -> dict:
    """When a NEW class is resolved, propose a known_classes entry (+ read-only probe)
    so it is auto-handled next time. recurrence -> 0. Probe respects the Phase-0 guard."""
    proposal = {"name": name, "match": match, "action": "probe" if handler else "escalate",
                "handler": handler, "fingerprint": fingerprint, "proposed_at": time.time()}
    os.makedirs(os.path.dirname(PROPOSALS), exist_ok=True)
    with open(PROPOSALS, "a") as f:
        f.write(json.dumps(proposal) + "\n")
    return proposal


def autonomy_ratio(conn, window_s: float = 7 * 86400) -> dict:
    """% of resolved tasks closed with NO human ping — the metric that tracks the founder's pain.
    remind_to_investigate must be 0 by construction (escalate() enforces diagnosis-first)."""
    since = time.time() - window_s
    rows = conn.execute(
        "SELECT id,status FROM tasks WHERE completed_at IS NOT NULL OR status='escalated'").fetchall()
    resolved = [r for r in rows]
    escalated = [r for r in resolved if r["status"] == "escalated"]
    auto = [r for r in resolved if r["status"] == "done"]
    # An escalation lacking a prior diagnosis = the disease. Must be 0.
    remind = sum(1 for r in escalated if not has_event(conn, r["id"], "diagnosis"))
    total = len(resolved) or 1
    return {"resolved": len(resolved), "auto_resolved": len(auto),
            "escalated": len(escalated), "autonomy_ratio": round(len(auto) / total, 3),
            "remind_to_investigate": remind}


def overnight_digest(conn, window_s: float = 86400) -> str:
    """'What Otto did overnight' — proactive trust-building summary."""
    since = time.time() - window_s
    done = conn.execute(
        "SELECT title FROM tasks WHERE status='done' AND completed_at>=?", (since,)).fetchall()
    esc = conn.execute(
        "SELECT title FROM tasks WHERE status='escalated'").fetchall()
    m = autonomy_ratio(conn)
    lines = [f"🌅 Otto overnight: {len(done)} resolved autonomously, {len(esc)} need you.",
             f"autonomy {int(m['autonomy_ratio']*100)}% · remind-to-investigate {m['remind_to_investigate']}"]
    for d in done[:8]:
        lines.append(f"  ✅ {d['title'][:80]}")
    for e in esc[:5]:
        lines.append(f"  🔵 {e['title'][:80]}")
    return "\n".join(lines)


# ── Daemon entrypoint ────────────────────────────────────────────────────────────
def run_daemon(interval_s: int = 60) -> None:
    conn = connect()
    init_db(conn)
    telegram_notify(f"🟢 coordinator online (pid {os.getpid()})")
    while True:
        try:
            tick(conn)
        except Exception as e:  # never die silently; surface and keep looping
            try:
                add_event(conn, "daemon", "loop_error", f"{type(e).__name__}: {str(e)[:200]}")
            except Exception:
                pass
        time.sleep(interval_s)


def _cli() -> int:
    import sys
    conn = connect()
    init_db(conn)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "once"
    if cmd == "daemon":
        run_daemon(int(os.environ.get("COORD_INTERVAL_S", "60")))
        return 0
    if cmd == "once":
        print(json.dumps(tick(conn)))
        return 0
    if cmd == "inject":
        tid = inject(conn, " ".join(sys.argv[2:]))
        print(tid or "(empty)")
        return 0
    if cmd == "approve":
        print("ok" if approve(conn, sys.argv[2]) else "not-pending")
        return 0
    if cmd == "digest":
        print(overnight_digest(conn))
        return 0
    if cmd == "metrics":
        print(json.dumps(autonomy_ratio(conn), indent=2))
        return 0
    sys.stderr.write("usage: coordinator.py [daemon|once|inject <text>|approve <id>|digest|metrics]\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(_cli())
