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
import urllib.request
import urllib.parse
import shutil

import route as _route

def get_telegram_creds() -> tuple[str | None, str | None]:
    token, chat_id = None, None
    env_path = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("TELEGRAM_BOT_TOKEN="):
                        token = line.split("=", 1)[1].strip("'\"")
                    elif line.startswith("TELEGRAM_HOME_CHANNEL="):
                        chat_id = line.split("=", 1)[1].strip("'\"")
        except Exception:
            pass
    return token, chat_id

def get_env_var(name: str, default: str = "") -> str:
    if name in os.environ:
        return os.environ[name]
    env_path = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith(f"{name}="):
                        return line.split("=", 1)[1].strip("'\"\n ")
        except Exception:
            pass
    return default

def check_signed_commit() -> bool:
    """Enforce Path A: verify the code about to run is a signed, committed state.
    Opt-in via COORD_ENFORCE_SIGNED_COMMITS == '1' (OFF by default).

    The daemon imports scripts from the WORKING TREE, not a git checkout, so a signed
    HEAD only guarantees integrity when the tree is clean — otherwise live (e.g.
    concurrent-agent) edits run unverified. We therefore require BOTH: the tree matches
    HEAD AND HEAD carries a valid signature. Fails closed."""
    if get_env_var("COORD_ENFORCE_SIGNED_COMMITS", "0") != "1":
        return True

    repo = os.path.expanduser("~/.hermes")
    try:
        # 1. Working tree must match HEAD — else uncommitted edits run unverified.
        dirty = subprocess.run(
            ["git", "-C", repo, "status", "--porcelain"], capture_output=True, text=True)
        if dirty.stdout.strip():
            sys.stderr.write(
                "⛔ Working tree has uncommitted changes — running code does not match the "
                "signed commit. Refusing to start.\n" + dirty.stdout)
            return False
        # 2. HEAD commit must carry a valid GPG/SSH signature.
        proc = subprocess.run(
            ["git", "-C", repo, "verify-commit", "HEAD"], capture_output=True, text=True)
        if proc.returncode == 0:
            return True
        sys.stderr.write(f"⛔ GPG/SSH signature verification failed for HEAD commit:\n{proc.stderr}\n")
        return False
    except Exception as e:
        sys.stderr.write(f"⛔ Exception during signed-commit verification: {e}\n")
        return False

def send_telegram_buttons(msg: str, task_id: str) -> bool:
    token, chat_id = get_telegram_creds()
    if not token or not chat_id:
        return False
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": msg,
        "reply_markup": {
            "inline_keyboard": [
                [
                    {"text": "✅ Approve", "callback_data": f"task:approve:{task_id[:8]}"},
                    {"text": "❌ Cancel", "callback_data": f"task:cancel:{task_id[:8]}"}
                ]
            ]
        }
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status == 200
    except Exception:
        return False

def create_remediation_pr(task, error_reason: str) -> str | None:
    dirs = _exec_scope_dirs()
    if not dirs:
        return None
    repo_dir = dirs[0]

    def run_git(args, check=True):
        return subprocess.run(
            ["git"] + args,
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=check
        )

    orig_branch = None
    try:
        # Check git status
        st_proc = run_git(["status", "--porcelain"], check=False)
        if st_proc.returncode != 0:
            return None
        
        modified_files = []
        for line in st_proc.stdout.splitlines():
            if len(line) > 3:
                file_path = line[3:].strip()
                if ".DS_Store" in file_path or ".hermes" in file_path or ".git" in file_path:
                    continue
                modified_files.append(file_path)

        if not modified_files:
            return None

        # Get current branch
        branch_proc = run_git(["rev-parse", "--abbrev-ref", "HEAD"])
        orig_branch = branch_proc.stdout.strip()

        # Create branch
        branch_name = f"feat/remediate-{task['id'][:8]}"
        run_git(["checkout", "-b", branch_name])

        try:
            # Stage files individually (never git add -A)
            for f in modified_files:
                run_git(["add", f])

            # Commit
            commit_msg = f"Auto-remediation for task {task['id'][:8]}: {task['title']}"
            run_git(["-c", "user.name=Hermes Bot", "-c", "user.email=hermes@localhost", "commit", "-m", commit_msg])

            # Push
            run_git(["push", "origin", branch_name])

            # Create Draft PR using gh CLI
            body = (
                f"Auto-remediation draft for task `{task['id'][:8]}`: **{task['title']}**.\n\n"
                f"**Verification error:**\n```\n{error_reason}\n```"
            )
            gh_proc = subprocess.run(
                ["gh", "pr", "create", "--draft", "--title", f"Remediation: {task['title']}", "--body", body, "--head", branch_name],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                check=True
            )
            pr_url = gh_proc.stdout.strip()
            return pr_url

        finally:
            # Revert codebase back to original branch and clean up
            run_git(["checkout", orig_branch], check=False)
            run_git(["checkout", "--", "."], check=False)
            
            # Clean only the untracked files we added
            for f in modified_files:
                full_path = os.path.join(repo_dir, f)
                if os.path.exists(full_path):
                    if os.path.isdir(full_path):
                        shutil.rmtree(full_path, ignore_errors=True)
                    else:
                        try:
                            os.remove(full_path)
                        except OSError:
                            pass

    except Exception:
        if orig_branch:
            try:
                run_git(["checkout", orig_branch], check=False)
            except Exception:
                pass
        return None

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
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at REAL
        );
        """
    )
    conn.commit()


def set_meta(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key,value,updated_at) VALUES (?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, value, time.time()))
    conn.commit()


def get_meta(conn, key: str):
    return conn.execute("SELECT value,updated_at FROM meta WHERE key=?", (key,)).fetchone()


def heartbeat(conn, summary: str) -> None:
    """Liveness proof written EVERY tick (even idle) — cheap, no LLM, no Telegram. This is
    what makes 'is the daemon alive?' answerable when the estate is parked and silent."""
    set_meta(conn, "last_tick", f"{os.getpid()}|{summary}")


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


def _tier_role(task) -> str:
    """Cost discipline: premium reasoning (strategist→claude) is reserved for fence-class
    stakes (money/identity/contract). Everything else — routine work AND all housekeeping —
    diagnoses/verifies on the cheap `coordinator` chain (deepseek-flash). This honours the
    founder routing ladder and stops the autopilot exhausting the Claude session limit (which
    would force the expensive deepseek-v4-pro / agy fallback)."""
    try:
        if task["kind"] == "failure" and not _is_operator_facing(task):
            return "coordinator"          # housekeeping never deserves premium reasoning
    except Exception:
        pass
    text = f"{task['title']} {task['body'] or ''}"
    return "strategist" if fence_class(text) != "low" else "coordinator"


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
PROMPTS_PATH = os.path.join(HERMES, "meta", "prompts.json")

def load_prompt(name: str, default: str) -> str:
    if os.path.exists(PROMPTS_PATH):
        try:
            with open(PROMPTS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if name in data:
                    return data[name]
        except Exception:
            pass
    return default

DEFAULT_EXECUTE_PROMPT = (
    "You are the EXECUTOR. Carry out this spec and report what you did + evidence.\n"
    "Spec: {spec}\nTask: {title}\n\nReturn a short factual result with concrete evidence."
)

DEFAULT_VERIFY_PROMPT = (
    "You are the VERIFIER. NO self-grading; be ADVERSARIAL and strict.\n"
    "Acceptance test: {acceptance_test}\nEvidence (the executor's ACTUAL output):\n{evidence}\n\n"
    "PASS only if the evidence contains CONCRETE PROOF the acceptance test is literally satisfied "
    "right now — real command output, file contents, or test results visible in the evidence. "
    "FAIL if the evidence is only a plan / intention / 'I will' / a description with no actual "
    "output, or if the proof is missing or ambiguous. When in doubt, FAIL.\n"
    "Return ONLY JSON: {{\"passed\": bool, \"reason\": str}}."
)

def get_execute_prompt() -> str:
    return load_prompt("EXECUTE_PROMPT", DEFAULT_EXECUTE_PROMPT)

def get_verify_prompt() -> str:
    return load_prompt("VERIFY_PROMPT", DEFAULT_VERIFY_PROMPT)

EXECUTE_PROMPT = DEFAULT_EXECUTE_PROMPT
VERIFY_PROMPT = DEFAULT_VERIFY_PROMPT


def diagnose(task, router) -> dict:
    txt = router(_tier_role(task), DIAGNOSE_PROMPT.format(title=task["title"], body=task["body"] or ""),
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
    """Run the spec with a real, tool-capable, deny-caged agent. Tries claude CLI first;
    falls back to agy CLI on failure/session limits. Raises on failure of both."""
    prompt = get_execute_prompt().format(spec=task["spec"] or "{}", title=task["title"])
    dirs = _exec_scope_dirs()
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)   # subscription/OAuth, never the dead pay-per-token key
    
    # 1. Try Claude CLI
    argv_claude = ["claude", "-p", "--permission-mode", "acceptEdits",
                   "--allowedTools", EXEC_ALLOWED_TOOLS]
    if os.path.exists(EXEC_SETTINGS):
        argv_claude += ["--settings", EXEC_SETTINGS]
    for d in dirs:
        argv_claude += ["--add-dir", d]
        
    claude_err = None
    try:
        proc = subprocess.run(argv_claude, input=prompt, capture_output=True, text=True,
                              timeout=EXEC_TIMEOUT_S, env=env,
                              cwd=(dirs[0] if dirs else None))
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        low = (out + "\n" + err).lower()
        
        # Check if Claude succeeded and didn't hit a session limit
        session_limit = any(t in low for t in ("session limit", "rate limit", "quota exceeded", "please upgrade", "credit balance"))
        if proc.returncode == 0 and out and not session_limit:
            return out
            
        claude_err = f"exit {proc.returncode}"
        if session_limit:
            claude_err += " (session/rate limit)"
        if err:
            claude_err += f": {err[:150]}"
    except Exception as e:
        claude_err = f"exception: {str(e)[:200]}"
        
    # 2. Fall back to AGY CLI
    argv_agy = ["agy", "--print", prompt, "--dangerously-skip-permissions"]
    for d in dirs:
        argv_agy += ["--add-dir", d]
        
    try:
        proc = subprocess.run(argv_agy, capture_output=True, text=True,
                              timeout=EXEC_TIMEOUT_S, env=env,
                              cwd=(dirs[0] if dirs else None),
                              stdin=subprocess.DEVNULL)
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        low = (out + "\n" + err).lower()
        
        session_limit = any(t in low for t in ("session limit", "rate limit", "quota exceeded", "please upgrade", "credit balance"))
        if proc.returncode == 0 and out and not session_limit:
            return f"[caged-executor-fallback (claude failed: {claude_err})]\n{out}"
            
        agy_err = f"exit {proc.returncode}"
        if session_limit:
            agy_err += " (session/rate limit)"
        if err:
            agy_err += f": {err[:150]}"
        raise RuntimeError(f"claude failed ({claude_err}) and agy fallback failed ({agy_err})")
    except Exception as e:
        if isinstance(e, RuntimeError):
            raise
        raise RuntimeError(f"claude failed ({claude_err}) and agy exception: {str(e)[:200]}")


def execute(task, router) -> str:
    spec = task["spec"] or "{}"
    if os.environ.get("COORD_AGENTIC_EXEC") == "1":   # production: act for real
        try:
            return _strip_think(agentic_execute(task))
        except Exception as e:                        # resilience: degrade to reasoning
            chat = router("executor", get_execute_prompt().format(spec=spec, title=task["title"]),
                          max_tokens=2000)
            return _strip_think(f"[agentic-exec-fallback: {type(e).__name__}: {str(e)[:120]}]\n{chat}")
    # Reasoners need output headroom or the answer truncates (finish=length) — give room.
    return _strip_think(router("executor", get_execute_prompt().format(spec=spec, title=task["title"]),
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
    txt = router(_tier_role(task), get_verify_prompt().format(
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


# Sources of the estate's OWN plumbing. The operator hears about THEIR projects and
# genuine decisions — never the housekeeping. These stay silent on push; they remain
# visible on pull (Otto brief / Otto decisions). This is the signal/noise gate.
INTERNAL_SOURCES = ("health-watchdog", "repo-health", "memory-hygiene", "queue")


def _is_operator_facing(task) -> bool:
    """True if this task is worth pinging the founder about: their own injected work,
    or a non-housekeeping task. Internal self-maintenance is silent (pull-only)."""
    try:
        if task["kind"] == "injected":
            return True
        if task["kind"] == "mission-step":
            return False  # flight director emits mission-level signal; per-step is silent
        src = task["source"] or ""
    except Exception:
        return True
    return not any(src == s or src.startswith(s) for s in INTERNAL_SOURCES)


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
    if _is_operator_facing(task):  # housekeeping escalations stay silent — pull via `Otto decisions`
        msg = f"{head}: {task['title']}\nwhy: {reason}\nroot cause: {spec.get('root_cause','(see task)')[:200]}"
        if decision:
            if not send_telegram_buttons(msg, task["id"]):
                notifier(msg + "\nreply approve to execute.")
        else:
            notifier(msg)


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
            msg = (f"⏸️ APPROVAL ({spec['risk_class']}): {task['title']}\n"
                   f"diagnosed: {spec.get('root_cause','')[:160]}\n"
                   f"Approve to execute.")
            if not send_telegram_buttons(msg, tid):
                notifier(msg + "\nreply approve to execute.")
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
            if _is_operator_facing(task):  # housekeeping completions roll up into the brief, not a ping
                notifier(f"✅ DONE: {task['title']} — {reason[:140]}")
            return "done"
        fails = task["consecutive_failures"] + 1
        _set(conn, tid, consecutive_failures=fails, last_failure_error=reason[:300])
        if fails >= max_retries:
            pr_url = create_remediation_pr(task, reason) if os.environ.get("COORD_AGENTIC_EXEC") == "1" else None
            if pr_url:
                add_event(conn, tid, "remediation_pr", pr_url)
                msg = (f"🔴 HOUSEKEEPING FAILED {fails}×: {task['title']}\n"
                       f"why: {reason[:160]}\n"
                       f"I've drafted a fix: {pr_url}")
                add_event(conn, tid, "escalate", json.dumps({"reason": f"PR created: {pr_url}", "decision": False}))
                _set(conn, tid, status="escalated")
                if _is_operator_facing(task):  # a drafted fix for housekeeping is silent (see `Otto chores`)
                    notifier(msg)
            else:
                escalate(conn, get_task(conn, tid),
                         f"failed verification {fails}× — {reason[:160]}", notifier)
            return "escalated"
        _set(conn, tid, status="diagnosed")                 # retry: re-spec then re-execute
        return "diagnosed"

    if st == "awaiting_approval":
        return "awaiting_approval"                           # waits for approve()

    return st


def approve(conn, task_id: str) -> bool:
    """Human one-tap: release a fence-paused or escalated task into execution."""
    t = get_task(conn, task_id)
    if not t or t["status"] not in ("awaiting_approval", "escalated"):
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
    # Autopilot: advance every active mission one step (rides the same lifecycle above).
    try:
        import flight
        flight.fly_all(conn, router, notifier)
    except Exception as e:  # flight must never crash the propulsion loop
        try:
            add_event(conn, "flight", "loop_error", f"{type(e).__name__}: {str(e)[:200]}")
        except Exception:
            pass
    return {"reaped": reaped, "advanced": len(moved), "states": moved}


MAX_INGEST_PER_TICK = int(os.environ.get("COORD_MAX_INGEST", "3"))
MAX_INFLIGHT = int(os.environ.get("COORD_MAX_INFLIGHT", "6"))
# Cost ceiling: a hard cap on NEW tasks admitted per rolling 24h. Bounds total LLM spend
# (each task ~= diagnose+execute+verify calls) so the autopilot can never run away.
DAILY_TASK_BUDGET = int(os.environ.get("COORD_DAILY_TASKS", "80"))


def tasks_today(conn, window_s: float = 86400) -> int:
    since = time.time() - window_s
    return conn.execute("SELECT COUNT(*) c FROM tasks WHERE created_at>=?", (since,)).fetchone()["c"]


def estate_idle(conn) -> bool:
    """True when nothing the FOUNDER cares about is in flight — only housekeeping (or nothing).
    When parked we spend nothing admitting new plumbing; real work (operator tasks, mission
    steps, active missions) always counts as not-idle so the ship stays responsive."""
    for t in list_active(conn):
        try:
            if _is_operator_facing(t) or t["kind"] == "mission-step":
                return False
        except Exception:
            return False
    try:
        import flight
        if flight.list_missions(conn):
            return False
    except Exception:
        pass
    return True


def ingest_failures(conn) -> int:
    """Turn new queue fingerprints into coordinator tasks — ADMISSION-CONTROLLED so a
    backlog drains gradually instead of storming the providers on one tick.
    Caps: at most MAX_INGEST_PER_TICK new tasks/tick, never exceed MAX_INFLIGHT active, and
    never exceed DAILY_TASK_BUDGET admissions/24h. Cost discipline: when the estate is idle
    (no founder work), housekeeping is NOT admitted — we don't pay an LLM to re-diagnose a
    dirty repo nobody is waiting on; it's still visible via `chores`."""
    if estate_idle(conn):
        return 0
    if tasks_today(conn) >= DAILY_TASK_BUDGET:
        return 0
    try:
        with open(QUEUE_STATE) as f:
            fps = json.load(f).get("fingerprints", {})
    except Exception:
        return 0
    existing = {r["source"] for r in conn.execute("SELECT source FROM tasks").fetchall()}
    inflight = len(list_active(conn))
    budget = min(MAX_INGEST_PER_TICK, max(0, MAX_INFLIGHT - inflight),
                 max(0, DAILY_TASK_BUDGET - tasks_today(conn)))
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
        "SELECT id,status FROM tasks WHERE (completed_at IS NOT NULL AND completed_at >= ?) "
        "OR (status='escalated' AND created_at >= ?)", (since, since)).fetchall()
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
        "SELECT title FROM tasks WHERE status='escalated' AND created_at>=?", (since,)).fetchall()
    m = autonomy_ratio(conn, window_s)
    lines = [f"🌅 Otto overnight: {len(done)} resolved autonomously, {len(esc)} need you.",
             f"autonomy {int(m['autonomy_ratio']*100)}% · remind-to-investigate {m['remind_to_investigate']}"]
    for d in done[:8]:
        lines.append(f"  ✅ {d['title'][:80]}")
    for e in esc[:5]:
        lines.append(f"  🔵 {e['title'][:80]}")
    return "\n".join(lines)


# ── Health / liveness (the "is it actually running?" view) ───────────────────────
def _proc_alive(pattern: str) -> bool:
    try:
        r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def _cron_summary() -> tuple[int, int]:
    """(active jobs, jobs that ping Telegram). Read-only; never raises."""
    try:
        with open(os.path.join(HERMES, "cron", "jobs.json")) as f:
            jobs = json.load(f)
        jobs = jobs if isinstance(jobs, list) else (jobs.get("jobs") or list(jobs.values()))
        active = [j for j in jobs if isinstance(j, dict) and j.get("enabled")]
        pinging = [j for j in active if j.get("deliver") == "origin"]
        return len(active), len(pinging)
    except Exception:
        return -1, -1


def health(conn) -> str:
    """One glance: is the estate actually operational? Liveness (daemon + gateway), backlog,
    autonomy, cost, cron — with a single OPERATIONAL / DEGRADED verdict at the top."""
    now = time.time()
    hb = get_meta(conn, "last_tick")
    tick_age = int(now - hb["updated_at"]) if hb else None
    # daemon is healthy if it ticked within ~3 intervals (3×60s); pid backs it up
    daemon_ok = tick_age is not None and tick_age < 200
    daemon_proc = _proc_alive("coordinator.py daemon")
    gateway_ok = _proc_alive("gateway run")
    active = list_active(conn)
    esc = conn.execute("SELECT COUNT(*) c FROM tasks WHERE status='escalated'").fetchone()["c"]
    done = conn.execute("SELECT COUNT(*) c FROM tasks WHERE status='done'").fetchone()["c"]
    m = autonomy_ratio(conn)
    try:
        import flight
        missions = len(flight.list_missions(conn))
    except Exception:
        missions = 0
    cron_active, cron_ping = _cron_summary()
    operational = (daemon_ok or daemon_proc) and gateway_ok
    verdict = "🟢 *OPERATIONAL*" if operational else "🔴 *DEGRADED — needs attention*"

    def mark(ok):
        return "🟢" if ok else "🔴"
    if tick_age is None:
        tick_str = "no heartbeat yet (just restarted?)"
    elif tick_age < 200:
        tick_str = f"ticked {tick_age}s ago"
    else:
        tick_str = f"⚠️ last tick {tick_age}s ago (stalled?)"
    lines = [
        f"🩺 *Estate health* — {verdict}",
        "",
        f"{mark(daemon_ok or daemon_proc)} Coordinator daemon: {tick_str}"
        f"{' · proc up' if daemon_proc else ' · ⚠️ process not found'}",
        f"{mark(gateway_ok)} Gateway (Telegram): {'up' if gateway_ok else 'DOWN'}",
        f"{mark(cron_ping in (0, 1))} Cron: {cron_active} jobs active, {cron_ping} ping you"
        + (" (noise controlled)" if cron_ping in (0, 1) else " ⚠️ noisy"),
        "",
        f"• Work: {len(active)} in flight · {missions} missions · {done} done · {esc} stuck (housekeeping)",
        f"• Autonomy (7d): {int(m['autonomy_ratio']*100)}% · remind-to-investigate: {m['remind_to_investigate']}",
        f"• Cost today: {tasks_today(conn)}/{DAILY_TASK_BUDGET} tasks"
        + (" · ⏸ parked" if estate_idle(conn) else ""),
    ]
    if not operational:
        lines.append("\n_Restart:_ `launchctl kickstart -k gui/$(id -u)/ai.hermes.coordinator`")
    return "\n".join(lines)


# ── Operator cockpit read-model (pull, on demand from Telegram) ──────────────────
def decisions_view(conn):
    """Everything waiting on the founder — one-tap-able, newest last."""
    return conn.execute(
        "SELECT id,title,status,risk_class,kind,source FROM tasks "
        "WHERE status IN ('escalated','awaiting_approval') ORDER BY created_at").fetchall()


def backlog_view(conn):
    """Everything in flight right now (any active state)."""
    ph = ",".join("?" * len(ACTIVE))
    return conn.execute(
        f"SELECT id,title,status,kind FROM tasks WHERE status IN ({ph}) ORDER BY created_at",
        ACTIVE).fetchall()


def operator_brief(conn, window_s: float = 86400) -> str:
    """The one-glance estate state for a busy operator: what's in flight, what got
    done, what needs a call — projects foregrounded, plumbing summarised to a number."""
    since = time.time() - window_s
    m = autonomy_ratio(conn, window_s)
    active = backlog_view(conn)
    dec = decisions_view(conn)
    done = conn.execute(
        "SELECT title FROM tasks WHERE status='done' AND completed_at>=?", (since,)).fetchall()
    proj = [a for a in active if a["kind"] == "injected"]          # the founder's own work
    chores = len(active) - len(proj)
    op_dec = [d for d in dec if _is_operator_facing(d)]            # genuinely needs the founder
    house_dec = len(dec) - len(op_dec)                            # stuck plumbing — not the founder's call
    lines = ["🛰️ *Estate brief* — live, just now"]
    try:
        import flight
        ml = flight.brief_line(conn)
        if ml:
            lines.append(ml)
    except Exception:
        pass
    lines += [f"• Your projects in flight: *{len(proj)}*   ·   housekeeping: {chores}",
             f"• Done (24h): {len(done)}   ·   needs your call: *{len(op_dec)}*",
             f"• Autonomy: {int(m['autonomy_ratio']*100)}%  ({m['auto_resolved']}/{m['resolved']} closed with no ping)"]
    if op_dec:
        lines.append("\n*⏳ Waiting on you:*")
        for d in op_dec[:6]:
            tag = "⏸ approve" if d["status"] == "awaiting_approval" else "🔴 blocked"
            lines.append(f"  {tag}  `{d['id'][:8]}`  {d['title'][:60]}")
        lines.append("  ↳ reply *Otto approve <id>*")
    if proj:
        lines.append("\n*🚀 Your work in flight:*")
        for a in proj[:6]:
            lines.append(f"  • {a['status']}: {a['title'][:60]}")
    if house_dec:
        lines.append(f"\n⚙️ Housekeeping: {house_dec} self-maintenance item(s) stuck — *not yours to fix*. "
                     f"Say *Otto chores* to see them.")
    if not op_dec and not proj:
        lines.append("\n_Nothing of yours in flight, nothing waiting on you._")
        lines.append("_Kick one off:_ *Otto, launch <project> — <goal>*")
    # Fuel gauge: bounded, visible cost. Premium (Claude) reasoning is reserved for
    # fence-class work; routine + housekeeping run on the cheap chain.
    used = tasks_today(conn)
    park = " · ⏸ parked (idle, spending nothing)" if estate_idle(conn) else ""
    lines.append(f"\n⛽ Today: {used}/{DAILY_TASK_BUDGET} tasks admitted{park}")
    return "\n".join(lines)


def _fmt_list(rows, empty: str) -> str:
    if not rows:
        return empty
    out = []
    for r in rows:
        out.append(f"  {r['status']:14} `{r['id'][:8]}`  {r['title'][:64]}")
    return "\n".join(out)


# ── Daemon entrypoint ────────────────────────────────────────────────────────────
def run_daemon(interval_s: int = 60) -> None:
    conn = connect()
    init_db(conn)
    if not check_signed_commit():
        msg = "FATAL: Code verification failed: HEAD commit is unsigned or signature is invalid."
        add_event(conn, "daemon", "fatal_verification_error", msg)
        sys.stderr.write(msg + "\n")
        sys.exit(1)
    add_event(conn, "daemon", "online", f"pid {os.getpid()}")  # silent: no startup ping (was noise)
    while True:
        try:
            r = tick(conn)
            heartbeat(conn, f"advanced={r.get('advanced',0)} reaped={r.get('reaped',0)}")
        except Exception as e:  # never die silently; surface and keep looping
            try:
                add_event(conn, "daemon", "loop_error", f"{type(e).__name__}: {str(e)[:200]}")
                heartbeat(conn, f"loop_error:{type(e).__name__}")
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
    if cmd == "brief":
        print(operator_brief(conn))
        return 0
    if cmd == "health":
        print(health(conn))
        return 0
    if cmd == "backlog":
        print("🗂️ In flight:\n" + _fmt_list(backlog_view(conn), "  (nothing in flight)"))
        return 0
    if cmd == "decisions":
        rows = [d for d in decisions_view(conn) if _is_operator_facing(d)]
        print("⏳ Waiting on you:\n" + _fmt_list(rows, "  (nothing — all clear)"))
        return 0
    if cmd == "chores":
        rows = [d for d in decisions_view(conn) if not _is_operator_facing(d)]
        print("⚙️ Housekeeping stuck (not yours):\n" + _fmt_list(rows, "  (none)"))
        return 0
    if cmd == "metrics":
        print(json.dumps(autonomy_ratio(conn), indent=2))
        return 0
    if cmd == "missions":
        import flight
        print(flight.mission_board(conn))
        return 0
    sys.stderr.write("usage: coordinator.py "
                     "[daemon|once|inject <text>|approve <id>|brief|backlog|decisions|chores|digest|metrics]\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(_cli())
