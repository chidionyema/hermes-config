"""otto-inbound — inbound Telegram bridge + ground-truth self-knowledge (Switch 2).

Two jobs, both via the gateway's `pre_gateway_dispatch` hook (sync, fires before auth):

1. GROUND-TRUTH SELF-ANSWERS. Questions about Otto's own model/status/config are
   answered deterministically by reading LIVE state (config.yaml + route.py + launchctl
   + the coordinator DB) — NOT by letting the chat model guess. This kills the
   "confidently says the wrong thing about itself" failure: it can never be stale.

2. TASK INJECTION. "Otto, <task>" DMs become tracked coordinator tasks (open →
   diagnose → execute → verify) instead of going to the default chat agent. Acks
   immediately; the coordinator daemon works it and reports completion.

Safety invariant: this hook MUST NEVER break inbound messaging. On ANY error it
returns {"action": "allow"} so the message falls through to normal dispatch.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys

logger = logging.getLogger("hermes.plugins.otto-inbound")

# The coordinator + router modules live in ~/.hermes/scripts (not importable by default).
_SCRIPTS = os.path.expanduser("~/.hermes/scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

_CONFIG = os.path.expanduser("~/.hermes/config.yaml")

# Resolve the hermes binary once — the gateway runs under launchd and may not have
# ~/.local/bin on PATH, so prefer an absolute path for the ack subprocess.
_HERMES = shutil.which("hermes") or os.path.expanduser("~/.local/bin/hermes")

# Optional "Otto," address prefix, stripped before intent-matching.
_ADDR = re.compile(r"^\s*otto[,:]?\s+", re.IGNORECASE)
# Address Otto with a payload (task trigger). Mirrors coordinator.inject()'s own regex.
_TRIGGER = re.compile(r"\s*otto[,:]?\s+\S", re.IGNORECASE)

# Self-knowledge intents (matched against text with any "Otto," prefix stripped).
_MODEL_Q = re.compile(
    r"\b(what|which|what'?s)\b.*\b(model|models|llm|brain|stack)\b"
    r"|\bwhat (are|do) you (run|running|use|using)\b"
    r"|\bwhat'?s your (model|setup|config|stack|brain)\b",
    re.IGNORECASE | re.DOTALL,
)
_STATUS_Q = re.compile(
    r"\b(your |system |full )?status\b|\bhealth\b"
    r"|\bare you (up|alive|ok|okay|working|running|online)\b"
    r"|\bis everything (up|ok|okay|working|running|fine)\b",
    re.IGNORECASE,
)


def _platform_name(src) -> str:
    p = getattr(src, "platform", "")
    return (getattr(p, "value", None) or str(p) or "").lower()


def _read_chat_model():
    """(provider, model, fallback_str) read LIVE from config.yaml — the authoritative
    chat brain, never the model's own guess."""
    import yaml  # gateway venv ships pyyaml (the plugin loader itself uses it)
    with open(_CONFIG) as f:
        cfg = yaml.safe_load(f) or {}
    m = cfg.get("model") or {}
    prov, model = m.get("provider", "?"), m.get("default", "?")
    fbs = cfg.get("fallback_providers") or []
    fb = ", ".join(f"{x.get('provider','?')}/{x.get('model','?')}" for x in fbs) if fbs else "none"
    return prov, model, fb


def _read_roles():
    """role -> 'prov/model → prov/model' chain string, LIVE from route.ROLE_CHAINS."""
    import route as RT
    return {role: " → ".join(f"{p}/{mdl or '(cli)'}" for p, mdl in chain)
            for role, chain in RT.ROLE_CHAINS.items()}


def _daemon_state(label: str) -> str:
    try:
        r = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=3)
        for ln in r.stdout.splitlines():
            if label in ln:
                pid = ln.split("\t")[0].strip()
                return f"up (pid {pid})" if pid and pid != "-" else "loaded (not running)"
        return "not loaded"
    except Exception:
        return "unknown"


def _status_block() -> str:
    parts = ["📊 *Live status (checked just now):*",
             f"• Gateway: {_daemon_state('ai.hermes.gateway')}",
             f"• Coordinator daemon: {_daemon_state('ai.hermes.coordinator')}"]
    try:
        import coordinator as C
        conn = C.connect()
        try:
            states = tuple(getattr(C, "ACTIVE", ("open", "diagnosed", "executing", "verifying")))
            ph = ",".join("?" * len(states))
            tot = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            act = conn.execute(f"SELECT COUNT(*) FROM tasks WHERE status IN ({ph})", states).fetchone()[0]
            done = conn.execute("SELECT COUNT(*) FROM tasks WHERE status='done'").fetchone()[0]
        finally:
            conn.close()
        parts.append(f"• Task queue: {act} active, {done} done, {tot} total")
    except Exception:
        parts.append("• Task queue: (unavailable)")
    return "\n".join(parts)


def _grounded_answer(text: str):
    """If `text` asks about Otto's own model/status, return a GROUND-TRUTH answer read
    live from config.yaml + route.py + launchctl. Else None. Never raises."""
    q = _ADDR.sub("", text or "").strip()
    is_model, is_status = bool(_MODEL_Q.search(q)), bool(_STATUS_Q.search(q))
    if not (is_model or is_status):
        return None
    lines = []
    try:
        if is_model:
            prov, model, fb = _read_chat_model()
            lines += ["🧠 *Verified live just now (read from config, not memory):*",
                      f"• Chat brain (this bot): *{prov} / {model}*",
                      f"  ↳ fallback: {fb}"]
            try:
                roles = _read_roles()
                lines.append("• Specialist roles (route.py):")
                for r in ("coordinator", "strategist", "executor"):
                    if r in roles:
                        lines.append(f"  ↳ {r}: {roles[r]}")
            except Exception:
                pass  # roles are a bonus; chat brain is the answer to the question
        if is_status:
            lines.append(_status_block())
    except Exception as e:
        logger.warning("otto-inbound: grounded answer failed: %s", e)
        return None
    return "\n".join(lines) if lines else None


def _ack(text: str) -> None:
    """Fire-and-forget Telegram send. Non-blocking (Popen, no wait) so it can never
    stall the gateway's event-loop thread. Best-effort."""
    try:
        subprocess.Popen(
            [_HERMES, "send", "--to", "telegram", text],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
        )
    except Exception as e:
        logger.warning("otto-inbound: send failed: %s", e)


def _on_inbound(event=None, gateway=None, session_store=None, **kwargs):
    """pre_gateway_dispatch callback (sync). Returns {"action": "skip"|"allow"}."""
    try:
        text = getattr(event, "text", "") or ""
        src = getattr(event, "source", None)

        # Telegram only — the founder's channel, where acks/answers/reports land.
        if "telegram" not in _platform_name(src):
            return {"action": "allow"}

        # (1) Ground-truth self-knowledge: answer model/status questions from LIVE
        # state so the chat model can never hallucinate its own setup. Checked BEFORE
        # the task trigger so "Otto, what model are you?" is answered, not injected.
        answer = _grounded_answer(text)
        if answer:
            logger.info("otto-inbound: grounded self-answer (model/status)")
            _ack(answer)
            return {"action": "skip", "reason": "answered from live state (ground truth)"}

        # (2) Task injection: "Otto, <task>" → tracked coordinator task.
        if not _TRIGGER.match(text):
            return {"action": "allow"}

        import coordinator as C
        conn = C.connect()
        try:
            C.init_db(conn)  # idempotent; ensures schema if daemon hasn't run yet
            who = getattr(src, "user_name", None) or getattr(src, "user_id", None) or "?"
            tid = C.inject(conn, text, created_by=f"telegram:{who}")
        finally:
            conn.close()

        if not tid:
            return {"action": "allow"}

        logger.info("otto-inbound: injected task %s from %s (%s)",
                    tid, who, getattr(src, "chat_id", "?"))
        _ack(f"🤖 On it — tracked as {tid[:8]}. I'll investigate and report back when it's done.")
        return {"action": "skip", "reason": f"routed to coordinator task {tid[:8]}"}

    except Exception as e:
        logger.warning("otto-inbound: hook error, falling through to normal dispatch: %s", e)
        return {"action": "allow"}


def register(ctx) -> None:
    ctx.register_hook("pre_gateway_dispatch", _on_inbound)
    logger.info("otto-inbound plugin registered (pre_gateway_dispatch → grounded answers + coordinator.inject)")
