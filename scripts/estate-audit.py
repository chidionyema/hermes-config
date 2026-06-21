#!/usr/bin/env python3
"""estate-audit.py — the FULL estate audit, reproducible on command (Telegram: "Otto audit").

Deterministic, no-LLM. Reads the estate's real state and judges it against fixed thresholds.
The principle is EXPOSE EVERYTHING — nothing hidden: runtime, autopilot, the operator surface,
work/spend, **self-improvement (RSI), self-reflection, self-healing (watchdog)**, missions &
milestones, every scheduled loop, governance/fence, assets, and repos. A one-off written report
goes stale within the hour; this command re-reads ground truth every time.

Shaped as a LOOP (loop-library discipline): OBSERVE fresh state → ASSESS against a fixed rubric
→ emit ONE named terminal VERDICT (HEALTHY/DEGRADED/BROKEN, never "ok" on an error) → HANDOFF
(what needs the operator). Best-effort: a failing probe degrades to a flag, never crashes.

Usage:  python3 estate-audit.py [--telegram]
Output: ~/.hermes/reports/ESTATE-AUDIT-<YYYY-MM-DD>.md  +  stdout (+ ===TELEGRAM=== block).
"""
from __future__ import annotations
import os, sys, sqlite3, subprocess, json, glob, datetime

HOME = os.path.expanduser("~")
HERMES = os.path.join(HOME, ".hermes")
COORD_DB = os.path.join(HERMES, "coordinator.db")
CONFIG = os.path.join(HERMES, "config.yaml")
REPORTS = os.path.join(HERMES, "reports")
OFF_SWITCH = os.path.join(HERMES, "meta", "OFF_SWITCH")  # present = RSI armed

DAEMONS = {
    "ai.hermes.gateway": ("Telegram gateway", True),
    "ai.hermes.coordinator": ("Autopilot coordinator", True),
    "ai.hermes.watchdog": ("Reliability watchdog", False),
    "ai.hermes.progress": ("Self-improvement progress", False),
    "ai.hermes.rsi": ("RSI learning loop", False),
}

findings: list[tuple[str, str]] = []  # (severity, message) — severity in {BROKEN, DEGRADED}


def add(sev: str, msg: str) -> None:
    findings.append((sev, msg))


def sh(cmd: list[str], timeout: int = 8) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def _ro():
    return sqlite3.connect(f"file:{COORD_DB}?mode=ro", uri=True, timeout=5)


def _one(conn, q, d=0):
    try:
        r = conn.execute(q).fetchone()
        return r[0] if r and r[0] is not None else d
    except Exception:
        return d


def _age(ts) -> str:
    try:
        secs = datetime.datetime.now().timestamp() - float(ts)
        if secs < 90:
            return "just now"
        if secs < 5400:
            return f"{int(secs//60)}m ago"
        if secs < 172800:
            return f"{int(secs//3600)}h ago"
        return f"{int(secs//86400)}d ago"
    except Exception:
        return "?"


# ---------------------------------------------------------------- 1. RUNTIME
def section_runtime() -> list[str]:
    out = ["## 1. Runtime (launchd daemons)"]
    state = {}
    for line in sh(["launchctl", "list"]).splitlines():
        p = line.split("\t")
        if len(p) == 3 and p[2] in DAEMONS:
            state[p[2]] = p[0]
    for label, (name, critical) in DAEMONS.items():
        pid = state.get(label, "absent")
        if pid not in ("-", "0", "absent", ""):
            out.append(f"- ✅ `{label}` — {name} (PID {pid})")
        else:
            out.append(f"- ❌ `{label}` — {name} **DOWN**")
            add("BROKEN" if critical else "DEGRADED",
                f"{name} (`{label}`) down — `launchctl kickstart -k gui/$(id -u)/{label}`")
    return out


# ---------------------------------------------------------------- 2. AUTOPILOT
def section_autopilot() -> list[str]:
    out = ["## 2. Autopilot (coordinator task loop)"]
    try:
        conn = _ro()
    except Exception as e:
        out.append(f"- ⚠️ coordinator.db unreadable: {e}")
        add("DEGRADED", "coordinator.db unreadable — autopilot state unknown")
        return out
    with conn:
        counts = dict(conn.execute("SELECT status, COUNT(*) FROM tasks GROUP BY status").fetchall())
        total = sum(counts.values())
        esc = counts.get("escalated", 0)
        active = sum(counts.get(s, 0) for s in ("open", "diagnosed", "executing", "verifying"))
        await_ = counts.get("awaiting_approval", 0)
        tick = _one(conn, "SELECT value FROM meta WHERE key='last_tick'", "")
    out.append(f"- Tasks: **{total}** — {counts.get('done',0)} done · {esc} escalated · "
               f"{active} active · {await_} awaiting-approval "
               f"({', '.join(f'{k}={v}' for k,v in sorted(counts.items()))})")
    out.append(f"- Last tick: `{tick or 'unknown'}`")
    if total and active == 0 and await_ == 0:
        add("BROKEN", f"Autopilot PARKED — 0 active tasks, {total} all terminal; the loop isn't advancing work.")
    if total and esc / total >= 0.5:
        add("BROKEN", f"{esc}/{total} tasks ({esc*100//total}%) escalated into SILENCE — no ask-for-help "
                      f"handoff fires; you're never told. (R3/R4)")
    if "advanced=0" in tick:
        add("DEGRADED", "Coordinator alive but last tick advanced 0 tasks — idling.")
    return out


# ---------------------------------------------------------------- 3. OPERATOR SURFACE
def section_surface() -> list[str]:
    out = ["## 3. Operator surface (does the estate speak first?)"]
    interval = None
    try:
        with open(CONFIG) as f:
            for line in f:
                if "gateway_notify_interval" in line:
                    interval = line.split(":", 1)[1].strip()
                    break
    except Exception:
        pass
    out.append(f"- `gateway_notify_interval`: `{interval}`  (0 = pull-only, estate never pings first)")
    if interval in ("0", "0.0", None):
        add("DEGRADED", "Estate never speaks first (`gateway_notify_interval: 0`) — nothing pings you "
                        "when a task blocks or needs approval. (R4)")
    return out


# ---------------------------------------------------------------- 4. SELF-IMPROVEMENT (RSI)
def section_rsi() -> list[str]:
    out = ["## 4. Self-improvement (RSI / learning loop)"]
    armed = os.path.exists(OFF_SWITCH)
    out.append(f"- Tuner: {'🟢 ARMED (runs nightly, stages candidates for approval)' if armed else '⚪ DISARMED (idle until armed)'}")
    proofs = sorted(glob.glob(os.path.join(HERMES, "meta", "proofs", "*.json")))
    out.append(f"- Self-signed receipts: {len(proofs)} (not counted as proof)")
    versions = os.path.join(HERMES, "meta", "improver-versions.jsonl")
    nver = sum(1 for _ in open(versions)) if os.path.exists(versions) else 0
    evalsets = len(glob.glob(os.path.join(HERMES, "meta", "rsi_evalsets", "*")))
    out.append(f"- Improver versions logged: {nver} · RSI eval-sets: {evalsets}")
    try:
        conn = _ro()
        with conn:
            n_ev = _one(conn, "SELECT COUNT(*) FROM evidence")
            last = conn.execute("SELECT verifier_verdict, ts FROM evidence ORDER BY ts DESC LIMIT 1").fetchone()
            # autonomy trend: first vs last snapshot
            snaps = conn.execute("SELECT autonomy_ratio, ts FROM progress_snapshots ORDER BY ts").fetchall()
        out.append(f"- Verified learning ledger: {n_ev} receipt(s)" +
                   (f"; last = {last[0]} ({_age(last[1])})" if last else " — none yet"))
        if snaps:
            a0, an = snaps[0][0], snaps[-1][0]
            arrow = "↗︎" if an > a0 else ("↘︎" if an < a0 else "→")
            out.append(f"- Autonomy trend: {a0*100:.0f}% {arrow} {an*100:.0f}% over {len(snaps)} snapshots")
            if n_ev == 0:
                add("DEGRADED", "RSI has zero VERIFIED learning receipts — self-improvement is unproven.")
    except Exception as e:
        out.append(f"- ⚠️ ledger/trend unavailable: {e}")
    if not armed:
        add("DEGRADED", "Self-improvement is DISARMED — the estate is not learning right now "
                        "(`Otto arm self-improvement` to enable).")
    return out


# ---------------------------------------------------------------- 5. SELF-REFLECTION
def section_reflection() -> list[str]:
    out = ["## 5. Self-reflection"]
    refl = sorted(glob.glob(os.path.join(HERMES, "logs", "reflection", "*.md")))
    if refl:
        latest = os.path.basename(refl[-1])
        age = _age(os.path.getmtime(refl[-1]))
        out.append(f"- {len(refl)} reflections; latest `{latest}` ({age})")
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        if today not in latest and age not in ("just now",) and "h ago" not in age:
            add("DEGRADED", f"No self-reflection today — latest is {latest}.")
    else:
        out.append("- No reflections found")
        add("DEGRADED", "Self-reflection has never run — no `logs/reflection/*.md`.")
    return out


# ---------------------------------------------------------------- 6. SELF-HEALING (watchdog)
def section_selfheal() -> list[str]:
    out = ["## 6. Self-healing (watchdog)"]
    try:
        conn = _ro()
        with conn:
            rows = conn.execute(
                "SELECT key, value FROM meta WHERE key LIKE 'watchdog%' ORDER BY key").fetchall()
    except Exception as e:
        out.append(f"- ⚠️ watchdog meta unreadable: {e}")
        return out
    if not rows:
        out.append("- No watchdog activity recorded")
        add("DEGRADED", "Watchdog has never recorded a run — self-healing unproven.")
        return out
    last_run = next((v for k, v in rows if k == "watchdog_last_run"), None)
    restarts = [(k, v) for k, v in rows if k.startswith("watchdog_restart:")]
    alerts = [(k, v) for k, v in rows if k.startswith("watchdog_alert:")]
    out.append(f"- Last run: {_age(last_run) if last_run else 'unknown'}")
    if restarts:
        out.append("- Auto-restarts performed: " +
                   ", ".join(f"{k.split(':',1)[1]} ({_age(v)})" for k, v in restarts))
    if alerts:
        out.append("- Wedge alerts seen: " +
                   ", ".join(f"{k.split(':',1)[1]} ({_age(v)})" for k, v in alerts))
    if last_run:
        try:
            if datetime.datetime.now().timestamp() - float(last_run) > 3600:
                add("DEGRADED", f"Watchdog last ran {_age(last_run)} — stale; it may not be self-healing.")
        except Exception:
            pass
    return out


# ---------------------------------------------------------------- 7. MISSIONS & MILESTONES
def section_missions() -> list[str]:
    out = ["## 7. Missions & milestones (the work portfolio)"]
    try:
        conn = _ro()
        with conn:
            missions = conn.execute("SELECT name, status, created_at FROM missions ORDER BY created_at").fetchall()
            ms = dict(conn.execute("SELECT status, COUNT(*) FROM milestones GROUP BY status").fetchall())
    except Exception as e:
        out.append(f"- ⚠️ missions unreadable: {e}")
        return out
    if missions:
        for name, status, _ in missions:
            mark = "✅" if status in ("done", "complete", "reached") else "🔧"
            out.append(f"- {mark} *{(name or '?')[:50]}* — {status}")
    else:
        out.append("- No missions")
    out.append(f"- Milestones: {sum(ms.values())} ({', '.join(f'{k}={v}' for k,v in sorted(ms.items())) or 'none'})")
    nondone = [s for _, s, _ in missions if s not in ("done", "complete", "reached")]
    if missions and len(nondone) == len(missions):
        add("DEGRADED", f"All {len(missions)} mission(s) unfinished — no operator project shipped. (R2)")
    return out


# ---------------------------------------------------------------- 8. SCHEDULED LOOPS (cron)
def section_cron() -> list[str]:
    out = ["## 8. Scheduled loops (cron)"]
    try:
        data = json.load(open(os.path.join(HERMES, "cron", "jobs.json")))
        jobs = data.get("jobs", data) if isinstance(data, dict) else data
    except Exception as e:
        out.append(f"- ⚠️ cron jobs.json unreadable: {e}")
        return out
    paused = []
    out.append(f"- {len(jobs)} jobs registered:")
    for j in jobs:
        name = j.get("name") or j.get("id") or "?"
        sch = j.get("schedule")
        disp = "?"
        if isinstance(sch, list) and sch and isinstance(sch[0], dict):
            disp = sch[0].get("display") or sch[0].get("expr") or sch[0].get("kind") or "?"
        elif isinstance(sch, dict):
            disp = sch.get("display") or sch.get("expr") or "?"
        on = j.get("enabled", True) and not j.get("paused")
        if not on:
            paused.append(name[:40])
        out.append(f"  - {'▶️' if on else '⏸'} {name[:48]}  `{disp}`")
    if paused:
        out.append(f"- ⏸ Paused: {', '.join(paused)}")
    return out


# ---------------------------------------------------------------- 9. GOVERNANCE / FENCE
def section_governance() -> list[str]:
    out = ["## 9. Governance & founder fence"]
    out.append(f"- Self-improvement OFF_SWITCH: {'ARMED' if os.path.exists(OFF_SWITCH) else 'DISARMED'}")
    try:
        conn = _ro()
        with conn:
            await_ = _one(conn, "SELECT COUNT(*) FROM tasks WHERE status='awaiting_approval'")
    except Exception:
        await_ = "?"
    out.append(f"- Tasks awaiting your approval (fence): {await_}")
    out.append("- Claude single-writer lane: `coordinator.py`, `config.yaml`, `plugins/otto-inbound/`, `gateway/`")
    out.append("- Fenced from all agents: money · identity · contract · migrations")
    return out


# ---------------------------------------------------------------- 10. ASSETS  11. REPOS
def section_assets() -> list[str]:
    out = ["## 10. Assets (scripts · specs · skills)"]
    py = len(glob.glob(os.path.join(HERMES, "scripts", "*.py")))
    sh_ = len(glob.glob(os.path.join(HERMES, "scripts", "*.sh")))
    specs = len(glob.glob(os.path.join(HERMES, "specs", "*.md")))
    skills = len(glob.glob(os.path.join(HOME, ".claude", "skills", "*")))
    out.append(f"- Scripts: {py} .py + {sh_} .sh · Specs: {specs} · Claude skills: {skills}")
    return out


def section_repos() -> list[str]:
    out = ["## 11. Git repos (uncommitted work)"]
    repos = [HERMES] + glob.glob(os.path.join(HOME, "Documents", "code", "*", ".git"))
    seen, dirty = set(), []
    for g in repos:
        root = os.path.realpath(g[:-5] if g.endswith("/.git") else g)
        if root in seen:
            continue
        seen.add(root)
        n = len([l for l in sh(["git", "-C", root, "status", "--porcelain"], 6).splitlines() if l.strip()])
        if n:
            dirty.append((os.path.basename(root), n))
    dirty.sort(key=lambda x: -x[1])
    out.append((f"- {len(dirty)} repos dirty (top): " + ", ".join(f"{n}={c}" for n, c in dirty[:6]))
               if dirty else "- All scanned repos clean")
    return out


# ---------------------------------------------------------------- VERDICT
def verdict():
    broken = [m for s, m in findings if s == "BROKEN"]
    degraded = [m for s, m in findings if s == "DEGRADED"]
    state = "🔴 BROKEN" if broken else ("🟠 DEGRADED" if degraded else "🟢 HEALTHY")
    lines = [f"## Verdict: {state}"]
    if broken:
        lines.append("\n**Broken (blocks the hands-off goal):**")
        lines += [f"- {m}" for m in broken]
    if degraded:
        lines.append("\n**Degraded (works, but not heavenly yet):**")
        lines += [f"- {m}" for m in degraded]
    if not broken and not degraded:
        lines.append("All subsystems within rubric. Estate operational.")
    return state, broken, degraded, lines


def main() -> int:
    now = datetime.datetime.now()
    stamp = now.strftime("%Y-%m-%d")
    sections = []
    for fn in (section_runtime, section_autopilot, section_surface, section_rsi,
               section_reflection, section_selfheal, section_missions, section_cron,
               section_governance, section_assets, section_repos):
        try:
            sections += fn() + [""]
        except Exception as e:
            sections += [f"## {fn.__name__} FAILED: {e}", ""]
            add("DEGRADED", f"audit probe {fn.__name__} crashed: {e}")
    state, broken, degraded, vlines = verdict()

    header = [f"# Estate Audit — {now.strftime('%Y-%m-%d %H:%M')}",
              "_Reproducible on command (`Otto audit`). Deterministic ground-truth, nothing hidden._", ""]
    body = "\n".join(header + vlines + [""] + sections)

    os.makedirs(REPORTS, exist_ok=True)
    path = os.path.join(REPORTS, f"ESTATE-AUDIT-{stamp}.md")
    try:
        open(path, "w").write(body)
    except Exception as e:
        print(f"(could not write report: {e})", file=sys.stderr)
    print(body)

    if "--telegram" in sys.argv:
        def short(m):
            return m.split(" — ")[0].split(" (R")[0]
        armed = os.path.exists(OFF_SWITCH)
        tg = [f"🩺 *Estate audit* — {state}", ""]
        if broken:
            tg.append("*Broken:*"); tg += [f"• {short(m)}" for m in broken[:5]]
        if degraded:
            tg.append("*Degraded:*"); tg += [f"• {short(m)}" for m in degraded[:6]]
        if not broken and not degraded:
            tg.append("All subsystems healthy ✅")
        tg += ["", f"_Self-improvement: {'ARMED' if armed else 'DISARMED'} · full report:_ `{path}`"]
        print("===TELEGRAM===")
        print("\n".join(tg))
        print("===TELEGRAM===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
