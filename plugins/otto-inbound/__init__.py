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

# Operator-cockpit pull commands. Read-only views of the estate, on demand.
_BRIEF_Q = re.compile(
    r"\b(brief|briefing|overview|sitrep|sit[- ]?rep|rundown|catch me up|fill me in"
    r"|what'?s going on|whats going on)\b", re.IGNORECASE)
_BACKLOG_Q = re.compile(
    r"\b(backlog|queue|in[- ]?flight|what'?s queued|whats queued|to[- ]?do list"
    r"|what are you working on)\b", re.IGNORECASE)
_DECISIONS_Q = re.compile(
    r"\b(decisions?|approvals?|what needs me|needs (my|your) (call|approval|decision)"
    r"|waiting on me|what'?s blocked|whats blocked)\b", re.IGNORECASE)
_CHORES_Q = re.compile(r"\b(chores|housekeeping|maintenance|plumbing)\b", re.IGNORECASE)
_HEALTH_Q = re.compile(
    r"\b(health|healthy|operational|are you (up|alive|running|ok|okay)|you (up|alive)"
    r"|is it (up|alive|running|working|operational)|status check|alive\?|diagnostics?"
    r"|heartbeat|everything ok|all good)\b", re.IGNORECASE)
_HELP_Q = re.compile(
    r"\b(help|commands?|menu|options|what can you do|what do you do|how do i use"
    r"|how to use|what can i (say|ask|do)|cheat ?sheet|how does this work"
    r"|how do i operate|guide)\b", re.IGNORECASE)
_REFLECT_Q = re.compile(
    r"\b(reflect|reflection|self.?improv\w*|improvements?|what did you learn"
    r"|retro|getting better|how are you improving)\b", re.IGNORECASE)

# ── Mission engine (autopilot) command surface ───────────────────────────────────
# "launch <name>: <goal>" sets a destination the ship will autonomously fly toward.
_LAUNCH_CMD = re.compile(r"^\s*launch\b\s+(.+)", re.IGNORECASE | re.DOTALL)
_MISSIONS_Q = re.compile(r"\bmissions\b|\bmission board\b|\bthe fleet\b", re.IGNORECASE)
_MISSION_DETAIL = re.compile(r"^\s*mission\s+(\S.+)", re.IGNORECASE | re.DOTALL)
_RESUME_CMD = re.compile(r"\bresume\b\s+`?([0-9a-fA-F]{4,})`?", re.IGNORECASE)
_ABORT_CMD = re.compile(r"\babort\b\s+`?([0-9a-fA-F]{4,})`?", re.IGNORECASE)
# One-tap founder approval: "Otto approve <8-char id>". Hex id keeps it from catching
# task phrases like "approve the budget".
_APPROVE_CMD = re.compile(r"\bapprove[ds]?\b\s+`?([0-9a-fA-F]{4,})`?", re.IGNORECASE)


def _platform_name(src) -> str:
    p = getattr(src, "platform", "")
    return (getattr(p, "value", None) or str(p) or "").lower()


def _read_chat_model():
    """(provider, model, fallback_str) read LIVE from config.yaml — the authoritative
    chat brain, never the model's own guess."""
    import yaml  # gateway venv ships pyyaml (the plugin loader itself uses it)
    with open(_CONFIG) as f:
        cfg = yaml.safe_load(f) or {}
    m = cfg.get("model")
    # `model:` may be a mapping ({provider, default}) OR a bare scalar slug — tolerate both
    # so a config reshape by another writer can't silently break the self-answer.
    if isinstance(m, dict):
        prov, model = m.get("provider", "?"), m.get("default") or m.get("model", "?")
    elif isinstance(m, str) and m.strip():
        prov, model = (cfg.get("provider") or "?"), m.strip()
    else:
        prov, model = "?", "?"
    if prov in ("?", "", None) and isinstance(model, str):
        for v in ("deepseek", "minimax", "claude", "anthropic", "gemini", "gpt", "openai"):
            if v in model.lower():
                prov = v
                break
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
            # Prefer the coordinator's rich health view (verdict + liveness heartbeat +
            # autonomy + cron + fuel); fall back to the basic status block if unavailable.
            try:
                import coordinator as C
                conn = C.connect()
                try:
                    lines.append(C.health(conn))
                finally:
                    conn.close()
            except Exception:
                lines.append(_status_block())
    except Exception as e:
        logger.warning("otto-inbound: grounded answer failed: %s", e)
        return None
    return "\n".join(lines) if lines else None


def _resolve_id(conn, prefix: str):
    """8-char prefix → full task id, only if unambiguous."""
    rows = conn.execute("SELECT id FROM tasks WHERE id LIKE ? LIMIT 2", (prefix + "%",)).fetchall()
    return rows[0][0] if len(rows) == 1 else None


def _approve_cmd(text: str):
    """If `text` is 'Otto approve <id>', release the paused task and return an ack. Else None."""
    m = _APPROVE_CMD.search(_ADDR.sub("", text or ""))
    if not m:
        return None
    pref = m.group(1)
    try:
        import coordinator as C
        conn = C.connect()
        try:
            full = _resolve_id(conn, pref)
            ok = bool(full) and C.approve(conn, full)
        finally:
            conn.close()
    except Exception as e:
        logger.warning("otto-inbound: approve failed: %s", e)
        return f"⚠️ Couldn't process approval for `{pref}` — try again or check *Otto decisions*."
    return (f"✅ Approved `{pref}` — releasing it to execution now."
            if ok else
            f"⚠️ `{pref}` isn't awaiting approval (already moving, done, or unknown). Try *Otto decisions*.")


def _mission_dispatch(text: str, who: str = "?"):
    """Autopilot command surface: launch / resume / abort / missions-board / mission-detail.
    Returns a reply string (→ ack + skip) or None (→ fall through). Never raises."""
    q = _ADDR.sub("", text or "").strip()
    try:
        import coordinator as C
        import flight as FL
    except Exception as e:
        logger.warning("otto-inbound: flight import failed: %s", e)
        return None
    try:
        m = _RESUME_CMD.search(q)
        if m:
            conn = C.connect()
            try:
                ok = FL.resume_mission(conn, m.group(1))
            finally:
                conn.close()
            return (f"▶️ Resuming mission `{m.group(1)}` — flying again."
                    if ok else f"⚠️ `{m.group(1)}` isn't a resumable mission. Try *Otto missions*.")
        m = _ABORT_CMD.search(q)
        if m:
            conn = C.connect()
            try:
                ok = FL.abort_mission(conn, m.group(1))
            finally:
                conn.close()
            return (f"🛑 Aborted mission `{m.group(1)}`."
                    if ok else f"⚠️ `{m.group(1)}` isn't an active mission.")
        m = _LAUNCH_CMD.match(q)
        if m:
            rest = m.group(1).strip()
            name, goal = rest, rest
            for sep in (":", "—", " - "):
                if sep in rest:
                    a, b = rest.split(sep, 1)
                    if a.strip() and b.strip():
                        name, goal = a.strip(), b.strip()
                        break
            else:
                name = " ".join(rest.split()[:5])  # no separator → name = opening words
            conn = C.connect()
            try:
                FL.create_mission(conn, name, goal, created_by=f"telegram:{who}")
            finally:
                conn.close()
            return (f"🚀 *Destination set — {name}.*\n"
                    f"🎯 {goal[:120]}\n"
                    f"Plotting the course now; first milestones appear within ~60s.\n"
                    f"Track it: *Otto missions*.")
        # board first so "mission board" / "missions" don't fall into detail
        if _MISSIONS_Q.search(q) and (q.rstrip().endswith("?") or len(q.split()) <= 4):
            conn = C.connect()
            try:
                return FL.mission_board(conn)
            finally:
                conn.close()
        m = _MISSION_DETAIL.match(q)
        if m:
            conn = C.connect()
            try:
                return FL.mission_detail(conn, m.group(1).strip())  # None if unknown → falls through
            finally:
                conn.close()
    except Exception as e:
        logger.warning("otto-inbound: mission command failed: %s", e)
    return None


def _help_text() -> str:
    """Plain-language menu of everything Otto can do — so the operator never has to
    memorise a single command. This IS the frictionless surface: ask in any words."""
    return (
        "🤖 *Otto — here's everything I can do.* Just DM me, plain English is fine.\n"
        "\n"
        "📊 *See what's going on*\n"
        "• `Otto health` — am I alive, is everything OK\n"
        "• `Otto brief` — the rundown right now\n"
        "• `Otto backlog` — what I'm working on\n"
        "• `Otto decisions` — what's waiting on *you*\n"
        "• `Otto reflect` — how I'm improving (daily ideas + receipts)\n"
        "\n"
        "✅ *Put me to work*\n"
        "• `Otto, <anything>` — I diagnose it and fix it (e.g. _Otto, the pricing page 404s_)\n"
        "• `Otto, launch <name>: <goal>` — start a whole project on autopilot\n"
        "• `Otto approve <id>` — release a money/identity task I paused for your OK\n"
        "\n"
        "⚙️ *Housekeeping (mine, not yours)*\n"
        "• `Otto chores` — internal maintenance I'm handling\n"
        "• `Otto missions` — the project autopilot board\n"
        "\n"
        "_You never need to remember these — just say *what can you do* anytime._"
    )


def _reflect_view() -> str:
    """Self-improvement tracker: latest daily reflection's improvement items + strategist
    audit pointer + RSI receipt activity. Reads files only (no DB). Always returns a string."""
    import glob, json, os as _os
    H = _os.path.expanduser("~/.hermes")
    out = ["🪞 *Self-improvement* — what I'm doing to get better"]

    # 1. Latest daily reflection — pull the 'Improvement Plan' items.
    refl = sorted(glob.glob(f"{H}/logs/reflection/*.md"))
    if refl:
        name = _os.path.basename(refl[-1]).replace(".md", "")
        items = []
        try:
            txt = open(refl[-1], encoding="utf-8").read()
            if "## 8. Improvement Plan" in txt:
                body = txt.split("## 8. Improvement Plan", 1)[1]
                for ln in body.splitlines()[1:]:
                    ln = ln.strip()
                    if ln and not ln.startswith("#"):
                        items.append(ln)
                    if len(items) >= 3:
                        break
        except OSError:
            pass
        out.append(f"\n📅 *Reflection ({name}):*")
        out += [f"  • {i}" for i in items] or ["  • (no improvement items logged)"]
    else:
        out.append("\n📅 *Reflection:* none yet (runs 6pm daily).")

    # 2. Latest strategist audit — structural improvement suggestions.
    audits = sorted(glob.glob(f"{H}/reports/strategist-audit-*.md"))
    if audits:
        out.append(f"\n🧭 *Strategist audit:* `{_os.path.basename(audits[-1])}` — open for structural ideas.")
    else:
        out.append("\n🧭 *Strategist audit:* none yet (runs 8am daily).")

    # 3. RSI receipts — proof of applied self-modifications.
    proofs = sorted(glob.glob(f"{H}/meta/proofs/*.json"))
    if proofs:
        att = "?"
        try:
            att = json.load(open(proofs[-1], encoding="utf-8")).get("attestation", "?")
        except (OSError, json.JSONDecodeError):
            pass
        out.append(f"\n🔐 *RSI receipts:* {len(proofs)} applied — latest: {str(att)[:70]}")
    else:
        out.append("\n🔐 *RSI receipts:* none yet — no self-modifications applied.")

    out.append("\n↳ *Otto brief* for live work · *Otto decisions* for what needs you.")
    return "\n".join(out)


def _cockpit_read(text: str):
    """Read-only cockpit views (help / health / brief / backlog / decisions) read LIVE
    from the coordinator DB. Returns a string or None. Query-like only (short / a
    question), so it never hijacks a real 'Otto, <task>' that contains a keyword."""
    q = _ADDR.sub("", text or "").strip()
    is_help = bool(_HELP_Q.search(q))
    is_reflect = bool(_REFLECT_Q.search(q))
    is_health = bool(_HEALTH_Q.search(q))
    is_brief = bool(_BRIEF_Q.search(q))
    is_backlog = bool(_BACKLOG_Q.search(q))
    is_chores = bool(_CHORES_Q.search(q))
    is_decisions = bool(_DECISIONS_Q.search(q)) and not is_chores
    if not (is_help or is_reflect or is_health or is_brief or is_backlog or is_decisions or is_chores):
        return None
    # Only treat as a pull command when it reads like a query, not an instruction.
    if not (q.rstrip().endswith("?") or len(q.split()) <= 6):
        return None
    # Static / file-only views — no DB needed, answer before touching the coordinator.
    if is_help:
        return _help_text()
    if is_reflect:
        return _reflect_view()
    try:
        import coordinator as C
        conn = C.connect()
        try:
            if is_health:
                return C.health(conn)
            if is_brief:
                return C.operator_brief(conn)
            if is_decisions:
                allrows = C.decisions_view(conn)
                rows = [r for r in allrows if C._is_operator_facing(r)]
                chores_n = len(allrows) - len(rows)
                if not rows:
                    tail = f" ({chores_n} housekeeping item(s) — *Otto chores*)" if chores_n else ""
                    return "✅ Nothing waiting on you — all clear." + tail
                out = ["⏳ *Waiting on you:*"]
                for r in rows[:10]:
                    tag = "⏸ approve" if r["status"] == "awaiting_approval" else "🔴 blocked"
                    out.append(f"  {tag}  `{r['id'][:8]}`  {r['title'][:60]}")
                out.append("\n↳ *Otto approve <id>* to release a paused task.")
                if chores_n:
                    out.append(f"_(+{chores_n} housekeeping — *Otto chores*)_")
                return "\n".join(out)
            if is_chores:
                rows = [r for r in C.decisions_view(conn) if not C._is_operator_facing(r)]
                if not rows:
                    return "⚙️ Housekeeping all clear — nothing stuck."
                out = ["⚙️ *Housekeeping stuck* (self-maintenance, not yours to fix):"]
                for r in rows[:12]:
                    out.append(f"  • {r['title'][:64]}")
                return "\n".join(out)
            if is_backlog:
                rows = C.backlog_view(conn)
                if not rows:
                    return "🗂️ Nothing in flight right now."
                out = ["🗂️ *In flight:*"]
                for r in rows[:12]:
                    mark = "🚀" if r["kind"] == "injected" else "🔧"
                    out.append(f"  {mark} {r['status']}: {r['title'][:60]}")
                return "\n".join(out)
        finally:
            conn.close()
    except Exception as e:
        logger.warning("otto-inbound: cockpit read failed: %s", e)
    return None


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

        who = getattr(src, "user_name", None) or getattr(src, "user_id", None) or "?"

        # (2) One-tap approval: "Otto approve <id>" releases a fence-paused task.
        approved = _approve_cmd(text)
        if approved is not None:
            logger.info("otto-inbound: approval command")
            _ack(approved)
            return {"action": "skip", "reason": "approval command"}

        # (3) Autopilot: launch a mission / fleet telemetry / resume / abort.
        mission = _mission_dispatch(text, who)
        if mission is not None:
            logger.info("otto-inbound: mission command")
            _ack(mission)
            return {"action": "skip", "reason": "mission command"}

        # (4) Operator cockpit: brief / backlog / decisions — live views, no chat model.
        view = _cockpit_read(text)
        if view:
            logger.info("otto-inbound: cockpit read")
            _ack(view)
            return {"action": "skip", "reason": "answered from coordinator read-model"}

        # (5) Task injection: "Otto, <task>" → tracked coordinator task.
        if not _TRIGGER.match(text):
            return {"action": "allow"}

        import coordinator as C
        conn = C.connect()
        try:
            C.init_db(conn)  # idempotent; ensures schema if daemon hasn't run yet
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
