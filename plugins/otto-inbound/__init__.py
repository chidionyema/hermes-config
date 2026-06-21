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

# War room + control surfaces. warroom.py is verified under the SYSTEM python (route.py +
# openai live there) — prefer it over the gateway venv so a venv dep gap can't break the panel.
_WARROOM_PY = os.path.join(_SCRIPTS, "warroom.py")
_SYS_PY = "/usr/local/bin/python3" if os.path.exists("/usr/local/bin/python3") else sys.executable
# Autonomous self-improvement switch: file PRESENT = armed (nightly RSI tuner runs),
# ABSENT = disarmed (tuner no-ops). Mirrors rsi-autorun.sh's guard.
_OFF_SWITCH = os.path.expanduser("~/.hermes/meta/OFF_SWITCH")

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
    r"|retro|getting better|how are you improving|progress|are you learning"
    r"|are you improving|is it working|recursive|trend)\b", re.IGNORECASE)

# ── Under-the-hood introspection (capabilities the cockpit didn't surface) ─────────
# CLASS 1 — live self-improvement (RSI) control-plane state (armed? last run? proof?).
_RSI_Q = re.compile(
    r"\b(rsi|tuner|auto.?tun\w*)\b"
    r"|\bself.?improv\w*\s+(status|state|running|armed|on|off)\b"
    r"|\bare you (tuning|auto.?tuning)\b"
    r"|\b(staged|candidate)\s+(improvement|change|merge)\b", re.IGNORECASE)
# CLASS 2 — on-demand diagnostics: "what's actually broken right now?" (estate/self-anchored
# so a task like "the pricing page is wrong" never matches).
_DIAG_Q = re.compile(
    r"\bdiagnos(e|tics?)\b|\bdrift\b|\bself.?check\b|\bwhat needs fixing\b"
    r"|\bscan (now|the estate|everything)\b|\bwhat'?s broken\b"
    r"|\banything (broken|failing|wrong with (you|the estate|the system))\b"
    r"|\bany (alerts|errors|failures|problems)\b", re.IGNORECASE)
# CLASS 3a — decision rationale: "Otto why [<id>]" → reconstruct what logic led to an outcome.
_WHY_CMD = re.compile(r"^\s*why\b\s*(.*)$|^\s*explain\b\s+(?:your|the|that)\s+"
                      r"(?:decision|reasoning|rationale|call)\b\s*(.*)$", re.IGNORECASE | re.DOTALL)
# CLASS 3b — memory recall: "Otto remember/recall <x>" / "what do you remember about <x>".
_RECALL_CMD = re.compile(
    r"^\s*(?:remember|recall|memor(?:y|ies)\s+(?:of|about)"
    r"|what do you (?:remember|know) about|what'?s in your memory about)\b\s*(.+)$",
    re.IGNORECASE | re.DOTALL)

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

# War room: "Otto, war room: <question>" / "Otto, convene a war room on <q>" convenes the
# multi-AI advisory panel. Anchored triggers only ('war room' / 'convene') so a normal task
# like "the admin panel is broken" can never be mistaken for a war room.
_WARROOM_CMD = re.compile(
    r"^\s*(?:war[\s-]?room|convene)\b\s*(?:a|the)?\s*(?:war[\s-]?room|panel|council)?"
    r"\s*(?:on|about|re)?\s*[:,\-–]?\s*(.+)", re.IGNORECASE | re.DOTALL)
# Autonomous self-improvement control. Both halves required (a verb AND the subject) so
# "are you learning?" (no verb) and "stop mission abcd" (no subject) never match here.
_ARM_CMD = re.compile(
    r"\b(arm|enable|turn on|switch on|re-?arm|allow)\b.*"
    r"\b(self.?improv\w*|learning|rsi|autonomy|auto.?tun\w*)\b", re.IGNORECASE | re.DOTALL)
_DISARM_CMD = re.compile(
    r"\b(disarm|disable|turn off|switch off|stop|halt|pause|freeze|kill)\b.*"
    r"\b(self.?improv\w*|learning|rsi|autonomy|auto.?tun\w*)\b", re.IGNORECASE | re.DOTALL)
# Whole-estate power switch (distinct from self-improvement above): the subject must be the
# ESTATE/everything, so "pause self-improvement" still routes to the RSI switch, not this.
_ESTATE_PATH = os.path.expanduser("~/.hermes/meta/ESTATE_PAUSED")
_ESTATE_PAUSE_CMD = re.compile(
    r"\b(pause|halt|freeze|stop|park|shut\s*down|shutdown|kill|hold)\b.*"
    r"\b(estate|everything|all\s+work|all\s+agents|all\s+tasks|the\s+ship|operations?)\b",
    re.IGNORECASE | re.DOTALL)
_ESTATE_RESUME_CMD = re.compile(
    r"\b(resume|unpause|un-?freeze|wake|restart|re-?start|start|unpark|go\s+live|reactivate)\b.*"
    r"\b(estate|everything|all\s+work|all\s+agents|all\s+tasks|the\s+ship|operations?)\b",
    re.IGNORECASE | re.DOTALL)
# Manual gateway bounce — makes the watchdog's "wedged gateway" alert actionable from the phone.
_GATEWAY_RESTART_CMD = re.compile(
    r"\b(restart|reboot|bounce|kick(?:start)?|reconnect|reset)\b.*\b(gateway|bot|telegram)\b",
    re.IGNORECASE | re.DOTALL)
_GATEWAY_LABEL = "ai.hermes.gateway"


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


def _warroom_cmd(text: str, who: str = "?"):
    """'Otto, war room: <question>' → convene the multi-AI advisory panel (DeepSeek + Claude
    CLI + AGY + MiniMax) as a DETACHED subprocess so the 2-3 min panel never blocks the
    gateway, then ack immediately. The panel DMs its chair's brief + each take when done."""
    q = _ADDR.sub("", text or "").strip()
    m = _WARROOM_CMD.match(q)
    if not m:
        return None
    question = (m.group(1) or "").strip().strip("?.! ")
    if len(question) < 6:
        return ("🗣️ A war room needs a question — try "
                "*Otto, war room: should we ship the auth rail before OIDC?*")
    try:
        subprocess.Popen(
            [_SYS_PY, _WARROOM_PY, question, "--who", str(who)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            cwd=_SCRIPTS,
        )
    except Exception as e:
        logger.warning("otto-inbound: war room spawn failed: %s", e)
        return "⚠️ Couldn't convene the war room just now — try again in a moment."
    return (f"🗣️ *War room convened.*\n❓ _{question[:200]}_\n"
            f"Polling DeepSeek, Claude & MiniMax in parallel (AGY too if its quota's live). "
            f"I'll DM the chair's brief + every take in ~1-3 min.")


def _gateway_restart_cmd(text: str):
    """Bounce the gateway from the phone (the actionable answer to a 'wedged gateway' alert).
    The gateway can't cleanly restart itself in-process, so we spawn a DETACHED helper that waits
    ~3s (so this ack reaches Telegram first) then `launchctl kickstart -k`s it. Returns a reply
    string or None. Never raises."""
    q = _ADDR.sub("", text or "").strip()
    if not _GATEWAY_RESTART_CMD.search(q):
        return None
    try:
        uid = os.getuid()
        # Detached: survives this process being killed by the very kickstart it launches.
        subprocess.Popen(
            ["/bin/sh", "-c",
             f"sleep 3; launchctl kickstart -k gui/{uid}/{_GATEWAY_LABEL}"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        return ("🔄 *Restarting the gateway now…* It'll drop offline for a few seconds, then "
                "Telegram reconnects. If it doesn't come back in ~30s, the box is likely "
                "overloaded — pull *Otto health*.")
    except Exception as e:
        logger.warning("otto-inbound: gateway restart cmd failed: %s", e)
        return "⚠️ Couldn't trigger a gateway restart — try again."


def _estate_power_cmd(text: str):
    """Whole-estate pause/resume from the phone — the CEO's big red switch. PAUSE makes the
    coordinator stop doing/spending (no task work, no missions) while still heartbeating and
    keeping the gateway + Telegram fully alive, so you stay in control. Pause wins ties
    (fail-safe). Returns a reply string or None. Never raises."""
    q = _ADDR.sub("", text or "").strip()
    pausing = bool(_ESTATE_PAUSE_CMD.search(q))
    resuming = bool(_ESTATE_RESUME_CMD.search(q))
    if not (pausing or resuming):
        return None
    try:
        os.makedirs(os.path.dirname(_ESTATE_PATH), exist_ok=True)
        if pausing:  # fail-safe: a "stop" intent always wins a tie
            with open(_ESTATE_PATH, "w") as fh:
                fh.write("paused via telegram\n")
            return ("⏸️ *ESTATE PAUSED.* The coordinator will stop starting task work and "
                    "missions (zero agent spend) on its next tick. Gateway + Telegram stay up — "
                    "you're still in control. Say *Otto resume the estate* to go live again.")
        if os.path.exists(_ESTATE_PATH):
            os.remove(_ESTATE_PATH)
        return ("▶️ *ESTATE RESUMED.* The coordinator will pick task work and missions back up "
                "on its next tick. Pull *Otto health* to confirm it's processing.")
    except Exception as e:
        logger.warning("otto-inbound: estate power cmd failed: %s", e)
        return "⚠️ Couldn't flip the estate switch — try again."


def _control_cmd(text: str):
    """Arm/disarm autonomous self-improvement from the phone. The OFF_SWITCH file gates the
    nightly RSI tuner (present = armed/runs, absent = disarmed/no-ops). Estate task-work is
    unaffected — this only governs the self-improvement loop. Disarm wins ties (fail-safe)."""
    q = _ADDR.sub("", text or "").strip()
    disarming = bool(_DISARM_CMD.search(q))
    arming = bool(_ARM_CMD.search(q))
    if not (arming or disarming):
        return None
    try:
        os.makedirs(os.path.dirname(_OFF_SWITCH), exist_ok=True)
        if disarming:  # fail-safe: a "stop" intent always wins
            if os.path.exists(_OFF_SWITCH):
                os.remove(_OFF_SWITCH)
            return ("🛑 *Self-improvement DISARMED.* The nightly RSI tuner will no-op until you "
                    "re-arm it. Your tasks, missions and the gateway keep running normally.")
        with open(_OFF_SWITCH, "w") as fh:
            fh.write("armed via telegram\n")
        return ("✅ *Self-improvement ARMED.* The nightly tuner will run — and it only ever "
                "*stages* a candidate for your approval, never auto-merges. Say *Otto disarm "
                "self-improvement* to stop it.")
    except Exception as e:
        logger.warning("otto-inbound: control cmd failed: %s", e)
        return "⚠️ Couldn't change the self-improvement switch — try again."


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
        "🔍 *Look under the hood*\n"
        "• `Otto rsi status` — is the self-improvement loop armed, when did it last run\n"
        "• `Otto diagnostics` — what's actually broken right now (alerts + drift)\n"
        "• `Otto why [<id>]` — the reasoning behind a decision (or my last one)\n"
        "• `Otto remember <topic>` — search what I know about something\n"
        "\n"
        "✅ *Put me to work*\n"
        "• `Otto, <anything>` — I diagnose it and fix it (e.g. _Otto, the pricing page 404s_)\n"
        "• `Otto, launch <name>: <goal>` — start a whole project on autopilot\n"
        "• `Otto approve <id>` — release a money/identity task I paused for your OK\n"
        "\n"
        "🗣️ *Convene a war room*\n"
        "• `Otto, war room: <question>` — DeepSeek + Claude + MiniMax (+AGY) debate it in\n"
        "   parallel; I DM you a decision brief in ~2 min\n"
        "\n"
        "🎛️ *Take control*\n"
        "• `Otto pause the estate` / `Otto resume the estate` — big red switch: stop/restart\n"
        "   all task work + missions (gateway stays up, you stay in control)\n"
        "• `Otto restart the gateway` — bounce the bot if Telegram feels stuck\n"
        "• `Otto arm self-improvement` / `Otto disarm self-improvement` — turn the nightly\n"
        "   auto-tuner on/off from your phone\n"
        "\n"
        "⚙️ *Housekeeping (mine, not yours)*\n"
        "• `Otto chores` — internal maintenance I'm handling\n"
        "• `Otto missions` — the project autopilot board\n"
        "\n"
        "_You never need to remember these — just say *what can you do* anytime._"
    )


def _reflect_view() -> str:
    """Self-improvement tracker. Leads with the independently-verified evidence
    ledger (the only claims that count) + autonomy trend from the coordinator DB,
    then daily-reflection ideas and demoted self-signed receipts. Always returns a string."""
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
            # Match the heading text, not its number — the reflection renumbers sections.
            if "Improvement Plan" in txt:
                body = txt.split("Improvement Plan", 1)[1]
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

    # 3. The EVIDENCE LEDGER — the only self-improvement claims that count.
    #    Independently verified, falsifiable proofs: a SEPARATE key signs the
    #    verdict and a no-delta proof goes RED. This is the source of truth for
    #    "is it actually learning?", replacing self-graded receipts.
    try:
        import coordinator as C
        import progress as P
        conn = C.connect()
        try:
            out.append("\n" + C.evidence_view(conn))
            out.append("\n" + P.view(conn))
        finally:
            conn.close()
    except Exception as e:
        logger.warning("otto-inbound: evidence/progress unavailable: %s", e)

    # 4. RSI receipts are self-signed by the writer — NOT proof. Surface only as
    #    raw activity, explicitly demoted, so they can never masquerade as verified.
    proofs = sorted(glob.glob(f"{H}/meta/proofs/*.json"))
    if proofs:
        out.append(f"\n🧾 _RSI activity: {len(proofs)} self-signed receipt(s) — not counted as proof; "
                   f"only the independently-verified ledger entries above are._")

    out.append("\n↳ *Otto brief* for live work · *Otto decisions* for what needs you.")
    return "\n".join(out)


def _rsi_status() -> str:
    """CLASS 1 — live self-improvement control-plane: armed/disarmed, last tuner activity,
    and the independently-verified evidence ledger (the only proof that counts). The cockpit
    previously only had the arm/disarm SWITCH and the historical *Otto reflect* view — never a
    'what is the loop doing right now' read. Always returns a string."""
    import glob, os as _os
    from datetime import datetime, timezone
    H = _os.path.expanduser("~/.hermes")
    armed = _os.path.exists(_OFF_SWITCH)  # file PRESENT = armed (see _OFF_SWITCH note)
    out = ["🧠 *Self-improvement (RSI) — live state:*",
           f"• Tuner: {'🟢 ARMED — runs nightly' if armed else '⚪ DISARMED — idle until you arm it'}"]
    proofs = sorted(glob.glob(f"{H}/meta/proofs/*.json"))
    if proofs:
        when = datetime.fromtimestamp(_os.path.getmtime(proofs[-1]), timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        out.append(f"• Last tuner run: {when}  ({len(proofs)} self-signed receipt(s), not counted as proof)")
    else:
        out.append("• Last tuner run: none yet")
    try:  # the verified ledger — separate-key signed, a no-delta proof goes RED
        import coordinator as C
        conn = C.connect()
        try:
            out.append("\n" + C.evidence_view(conn))
        finally:
            conn.close()
    except Exception as e:
        logger.warning("otto-inbound: rsi evidence unavailable: %s", e)
    tail = "*Otto disarm self-improvement* to stop it" if armed else "*Otto arm self-improvement* to enable it"
    out.append(f"\n↳ {tail} · *Otto reflect* for the full history.")
    return "\n".join(out)


def _diagnostics() -> str:
    """CLASS 2 — on-demand 'what's actually broken right now'. Reads the freshest watchdog
    alerts + drift/optimization reports (fast file reads, no heavy scan so the gateway never
    blocks). The estate auto-scans on cron; this just exposes the current known state. String."""
    import glob, json as _json, os as _os
    from datetime import datetime, timezone
    H = _os.path.expanduser("~/.hermes")
    out = ["🩺 *Estate diagnostics — latest known state:*"]
    latest_summary, problems = None, []
    alerts_p = f"{H}/logs/alerts/watchdog.jsonl"
    if _os.path.exists(alerts_p):
        try:
            for ln in reversed(open(alerts_p, encoding="utf-8").read().splitlines()[-80:]):
                try:
                    a = _json.loads(ln)
                except Exception:
                    continue
                if a.get("type") == "watchdog_summary":
                    if latest_summary is None:
                        latest_summary = a
                    # a summary only counts as a problem if it actually flagged alerts
                    ac = str(a.get("alert_count", "0")).strip()
                    av = a.get("alerts")
                    av_empty = (not av) or av == "[]"  # handles [] (list), "[]" (str), "", None
                    if ac not in ("0", "0.0", "") or not av_empty:
                        problems.append(a.get("message") or "watchdog alert")
                else:  # a discrete alert event, not a routine heartbeat
                    problems.append(a.get("message") or a.get("alert") or a.get("detail") or str(a))
                if len(problems) >= 4 and latest_summary is not None:
                    break
        except OSError:
            pass
    if latest_summary is not None:
        healthy = str(latest_summary.get("healthy")) == "True"
        loop = str(latest_summary.get("restart_loop")) == "True"
        dup = str(latest_summary.get("daemon_up")) == "True"
        verdict = "🟢 healthy" if (healthy and not loop) else "🔴 issues"
        extra = "" if dup else ", daemon DOWN"
        extra += ", restart-loop!" if loop else ""
        out.append(f"\n🛡️ *Watchdog:* {verdict} (as of {latest_summary.get('timestamp', '?')}){extra}")
    else:
        out.append("\n🛡️ *Watchdog:* no runs logged yet.")
    if problems:
        out.append("⚠️ *Active alerts:*")
        out += [f"  • {' '.join(str(p).split())[:100]}" for p in problems[:4]]
    elif latest_summary is not None:
        out.append("  • no active alerts")
    for label, path in (("Drift", f"{H}/reports/estate-drift.md"),
                        ("Optimization", f"{H}/reports/estate-optimization.md")):
        if _os.path.exists(path):
            mt = datetime.fromtimestamp(_os.path.getmtime(path), timezone.utc).strftime("%m-%d %H:%M UTC")
            head = ""
            try:
                for ln in open(path, encoding="utf-8"):
                    s = ln.strip().lstrip("#").strip()
                    if s:
                        head = s[:90]
                        break
            except OSError:
                pass
            out.append(f"\n📄 *{label}* (as of {mt}): {head}")
    out.append("\n↳ *Otto health* for the live verdict · *Otto chores* for stuck items.")
    return "\n".join(out)


def _why_view(m) -> str:
    """CLASS 3a — reconstruct the decision logic behind an outcome via otto-why.py. `m` is the
    _WHY_CMD match; group(1)/group(2) hold any payload. otto-why takes a task id or 'last'."""
    arg = ((m.group(1) or "") + " " + (m.group(2) or "")).strip()
    idm = re.search(r"`?([0-9a-fA-F]{6,})`?", arg)
    target = idm.group(1) if idm else "last"
    try:
        r = subprocess.run([_SYS_PY, os.path.join(_SCRIPTS, "otto-why.py"), target],
                           capture_output=True, text=True, timeout=20, cwd=_SCRIPTS)
        body = re.sub(r"\n\(Report saved to .*?\)\s*$", "", (r.stdout or "").strip()).strip()
        if not body:
            return f"🤔 No decision trace for `{target}`. Try *Otto why* (the last one) or *Otto decisions*."
        if len(body) > 1600:
            body = body[:1600] + "\n… _(truncated — full report in ~/.hermes/logs)_"
        return f"🧩 *Why — `{target}`*\n{body}"
    except subprocess.TimeoutExpired:
        return "⏱️ Rationale reconstruction took too long — try again."
    except Exception as e:
        logger.warning("otto-inbound: why cmd failed: %s", e)
        return "⚠️ Couldn't reconstruct that decision — try again."


def _recall_view(query: str) -> str:
    """CLASS 3b — search the estate's memory via memory_retrieval.py and surface what it knows.
    (Semantic layer needs numpy/onnx; falls back to tag-only otherwise — still useful.) String."""
    query = (query or "").strip().strip("?.! ")
    if len(query) < 2:
        return "🔎 What should I recall? Try *Otto remember the auth-rail decision*."
    try:
        r = subprocess.run([_SYS_PY, os.path.join(_SCRIPTS, "memory_retrieval.py"), query],
                           capture_output=True, text=True, timeout=25, cwd=_SCRIPTS)
        txt = r.stdout or ""
        mem = re.search(r"\[RETRIEVED MEMORY.*", txt, re.DOTALL)  # skip injection boilerplate
        body = (mem.group(0) if mem else txt).strip()
        if not body:
            return f"🔎 Nothing in memory about *{query[:60]}* yet."
        if len(body) > 1500:
            body = body[:1500] + "\n… _(truncated)_"
        return f"🧠 *Recall — {query[:60]}*\n```\n{body}\n```"
    except subprocess.TimeoutExpired:
        return "⏱️ Memory search took too long — try again."
    except Exception as e:
        logger.warning("otto-inbound: recall cmd failed: %s", e)
        return "⚠️ Couldn't search memory just now — try again."


def _introspect(text: str):
    """Under-the-hood reads the cockpit never exposed: live RSI state, on-demand diagnostics,
    decision rationale (why) and memory recall. Returns a string (→ ack + skip) or None. The
    why/recall verbs are command-style (explicit leading verb + payload); rsi/diag are query-style
    (short or a question) so they can't hijack a real 'Otto, <task>' that mentions a keyword."""
    q = _ADDR.sub("", text or "").strip()
    try:
        mw = _WHY_CMD.match(q)
        if mw:
            return _why_view(mw)
        mr = _RECALL_CMD.match(q)
        if mr:
            return _recall_view(mr.group(1))
        is_rsi, is_diag = bool(_RSI_Q.search(q)), bool(_DIAG_Q.search(q))
        if not (is_rsi or is_diag):
            return None
        if not (q.rstrip().endswith("?") or len(q.split()) <= 7):
            return None
        return _rsi_status() if is_rsi else _diagnostics()
    except Exception as e:
        logger.warning("otto-inbound: introspect failed: %s", e)
        return None


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

        # (3.5) War room: convene the multi-AI advisory panel (detached, DMs its brief).
        warroom = _warroom_cmd(text, who)
        if warroom is not None:
            logger.info("otto-inbound: war room command")
            _ack(warroom)
            return {"action": "skip", "reason": "war room convened"}

        # (3.55) Gateway bounce: make the watchdog's 'wedged gateway' alert actionable.
        gw_restart = _gateway_restart_cmd(text)
        if gw_restart is not None:
            logger.info("otto-inbound: gateway restart command")
            _ack(gw_restart)
            return {"action": "skip", "reason": "gateway restart"}

        # (3.6) Estate power: pause/resume ALL task work + missions (the big red switch).
        power = _estate_power_cmd(text)
        if power is not None:
            logger.info("otto-inbound: estate power command")
            _ack(power)
            return {"action": "skip", "reason": "estate power"}

        # (3.7) Control: arm/disarm autonomous self-improvement (OFF_SWITCH).
        control = _control_cmd(text)
        if control is not None:
            logger.info("otto-inbound: self-improvement control command")
            _ack(control)
            return {"action": "skip", "reason": "self-improvement control"}

        # (3.8) Introspection: live RSI state / on-demand diagnostics / why / memory recall.
        introspect = _introspect(text)
        if introspect is not None:
            logger.info("otto-inbound: introspection command")
            _ack(introspect)
            return {"action": "skip", "reason": "introspection read-model"}

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
