#!/usr/bin/env python3
"""estate-audit.py — the FULL estate audit, reproducible on command (Telegram: "Otto audit").

This is the on-demand, deterministic version of the by-hand ground-truth audit. It runs NO
LLM: it reads the estate's real state (launchd, coordinator.db, config, cron, repos) and judges
it against fixed thresholds. Because the estate's state drifts hour to hour (daemons fall over,
the autopilot parks), a one-off written report goes stale immediately — this command is the fix.

It is itself shaped as a LOOP (loop-library discipline):
  OBSERVE  → read fresh ground truth from disk/db (never trust a cached report)
  ASSESS   → score each subsystem against a fixed, observable rubric
  VERDICT  → emit ONE named terminal state: HEALTHY · DEGRADED · BROKEN  (never "ok" on an error)
  HANDOFF  → list exactly WHAT NEEDS THE OPERATOR (the loop's ask-for-help output)

Usage:
  python3 estate-audit.py            # write report + print full markdown
  python3 estate-audit.py --telegram # also print a compact block between ===TELEGRAM=== markers

Output: ~/.hermes/reports/ESTATE-AUDIT-<YYYY-MM-DD>.md  (full)  +  stdout.
Best-effort: a failing probe degrades to "unknown" and is flagged, it never crashes the audit.
"""
from __future__ import annotations
import os, sys, sqlite3, subprocess, json, glob, datetime

HOME = os.path.expanduser("~")
HERMES = os.path.join(HOME, ".hermes")
COORD_DB = os.path.join(HERMES, "coordinator.db")
CONFIG = os.path.join(HERMES, "config.yaml")
REPORTS = os.path.join(HERMES, "reports")

# Subsystems we expect alive. label -> (human name, critical?)
DAEMONS = {
    "ai.hermes.gateway": ("Telegram gateway", True),
    "ai.hermes.coordinator": ("Autopilot coordinator", True),
    "ai.hermes.watchdog": ("Reliability watchdog", False),
    "ai.hermes.progress": ("Self-improvement progress", False),
    "ai.hermes.rsi": ("RSI learning loop", False),
}

findings: list[tuple[str, str]] = []  # (severity, message); severity in {BROKEN, DEGRADED, OK}


def add(sev: str, msg: str) -> None:
    findings.append((sev, msg))


def sh(cmd: list[str], timeout: int = 8) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


# ---------------------------------------------------------------- 1. RUNTIME
def section_runtime() -> list[str]:
    out = ["## 1. Runtime (launchd daemons)"]
    listing = sh(["launchctl", "list"])
    state = {}
    for line in listing.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[2] in DAEMONS:
            pid = parts[0]
            state[parts[2]] = pid
    for label, (name, critical) in DAEMONS.items():
        pid = state.get(label, "absent")
        alive = pid not in ("-", "0", "absent", "")
        if alive:
            out.append(f"- ✅ `{label}` — {name} (PID {pid})")
        else:
            mark = "BROKEN" if critical else "DEGRADED"
            out.append(f"- ❌ `{label}` — {name} **DOWN** (pid={pid})")
            add(mark, f"{name} daemon (`{label}`) is down — `launchctl kickstart -k gui/$(id -u)/{label}`")
    return out


# ---------------------------------------------------------------- 2. AUTOPILOT
def section_autopilot() -> list[str]:
    out = ["## 2. Autopilot (coordinator task loop)"]
    try:
        conn = sqlite3.connect(f"file:{COORD_DB}?mode=ro", uri=True, timeout=5)
    except Exception as e:
        out.append(f"- ⚠️ cannot open coordinator.db: {e}")
        add("DEGRADED", "coordinator.db unreadable — autopilot state unknown")
        return out
    with conn:
        counts = dict(conn.execute("SELECT status, COUNT(*) FROM tasks GROUP BY status").fetchall())
        total = sum(counts.values()) or 0
        esc = counts.get("escalated", 0)
        active = sum(counts.get(s, 0) for s in ("open", "diagnosed", "executing", "verifying"))
        done = counts.get("done", 0)
        tick = ""
        try:
            row = conn.execute("SELECT value FROM meta WHERE key='last_tick'").fetchone()
            tick = row[0] if row else ""
        except Exception:
            pass
    out.append(f"- Tasks: **{total}** total — {done} done · {esc} escalated · {active} active "
               f"({', '.join(f'{k}={v}' for k, v in sorted(counts.items()))})")
    out.append(f"- Last tick: `{tick or 'unknown'}`")
    # Rubric
    if total and active == 0:
        add("BROKEN", f"Autopilot PARKED — 0 active tasks, {total} all terminal. The loop isn't advancing work.")
    if total and esc / total >= 0.5:
        add("BROKEN", f"{esc}/{total} tasks ({esc*100//total}%) escalated into SILENCE — no ask-for-help "
                      f"handoff fires; the operator is never told. (R3/R4)")
    if "advanced=0" in tick:
        add("DEGRADED", "Coordinator alive but every tick advances 0 tasks — engine idling, not working.")
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
    out.append(f"- `gateway_notify_interval`: `{interval}`")
    if interval in ("0", "0.0", None):
        add("DEGRADED", "Estate never speaks first (`gateway_notify_interval: 0`) — pure pull model, "
                        "nothing pings you when a task blocks or needs approval. (R4)")
    return out


# ---------------------------------------------------------------- 4. WORK & LEARNING
def section_work() -> list[str]:
    out = ["## 4. Work, spend & learning"]
    try:
        conn = sqlite3.connect(f"file:{COORD_DB}?mode=ro", uri=True, timeout=5)
    except Exception:
        out.append("- ⚠️ coordinator.db unreadable")
        return out
    with conn:
        def one(q, d=0):
            try:
                r = conn.execute(q).fetchone()
                return r[0] if r and r[0] is not None else d
            except Exception:
                return d
        missions = one("SELECT COUNT(*) FROM missions")
        blocked = one("SELECT COUNT(*) FROM missions WHERE status NOT IN ('done','complete')")
        proofs = one("SELECT COUNT(*) FROM evidence")
        spend = one("SELECT ROUND(SUM(CAST(cost_usd AS REAL)),4) FROM telemetry", 0)
        events = one("SELECT COUNT(*) FROM events")
    out.append(f"- Missions: {missions} ({blocked} not-done) · Evidence proofs: {proofs} · "
               f"Events: {events} · Spend: ${spend}")
    if missions and blocked == missions:
        add("DEGRADED", f"All {missions} missions stuck (none done) — zero operator projects shipped. (R2)")
    return out


# ---------------------------------------------------------------- 5. CRON
def section_cron() -> list[str]:
    out = ["## 5. Scheduled jobs (cron)"]
    jf = os.path.join(HERMES, "cron", "jobs.json")
    try:
        with open(jf) as f:
            data = json.load(f)
        jobs = data.get("jobs", data) if isinstance(data, dict) else data
        n = len(jobs)
        out.append(f"- {n} cron jobs registered")
    except Exception as e:
        out.append(f"- ⚠️ cron jobs.json unreadable: {e}")
    return out


# ---------------------------------------------------------------- 6. ASSETS
def section_assets() -> list[str]:
    out = ["## 6. Assets (scripts · specs · skills)"]
    py = len(glob.glob(os.path.join(HERMES, "scripts", "*.py")))
    sh_ = len(glob.glob(os.path.join(HERMES, "scripts", "*.sh")))
    specs = len(glob.glob(os.path.join(HERMES, "specs", "*.md")))
    skills = len(glob.glob(os.path.join(HOME, ".claude", "skills", "*")))
    out.append(f"- Scripts: {py} .py + {sh_} .sh · Specs: {specs} · Claude skills: {skills}")
    return out


# ---------------------------------------------------------------- 7. REPOS
def section_repos() -> list[str]:
    out = ["## 7. Git repos (uncommitted work)"]
    # Bounded: only known estate repos, short timeout each, count dirty.
    repos = [HERMES] + glob.glob(os.path.join(HOME, "Documents", "code", "*", ".git"))
    seen, dirty = set(), []
    for g in repos:
        root = g[:-5] if g.endswith("/.git") else g
        root = os.path.realpath(root)
        if root in seen:
            continue
        seen.add(root)
        st = sh(["git", "-C", root, "status", "--porcelain"], timeout=6)
        n = len([l for l in st.splitlines() if l.strip()])
        if n:
            dirty.append((os.path.basename(root), n))
    dirty.sort(key=lambda x: -x[1])
    if dirty:
        out.append(f"- {len(dirty)} repos with uncommitted changes (top): " +
                   ", ".join(f"{name}={n}" for name, n in dirty[:6]))
    else:
        out.append("- All scanned repos clean")
    return out


# ---------------------------------------------------------------- VERDICT
def verdict() -> tuple[str, list[str]]:
    broken = [m for s, m in findings if s == "BROKEN"]
    degraded = [m for s, m in findings if s == "DEGRADED"]
    if broken:
        state = "🔴 BROKEN"
    elif degraded:
        state = "🟠 DEGRADED"
    else:
        state = "🟢 HEALTHY"
    lines = [f"## Verdict: {state}"]
    if broken:
        lines.append("\n**Broken (blocks the hands-off goal):**")
        lines += [f"- {m}" for m in broken]
    if degraded:
        lines.append("\n**Degraded (works, but not heavenly yet):**")
        lines += [f"- {m}" for m in degraded]
    if not broken and not degraded:
        lines.append("All subsystems within rubric. Estate is operational.")
    return state, lines


def main() -> int:
    now = datetime.datetime.now()
    stamp = now.strftime("%Y-%m-%d")
    sections = []
    for fn in (section_runtime, section_autopilot, section_surface,
               section_work, section_cron, section_assets, section_repos):
        try:
            sections += fn() + [""]
        except Exception as e:
            sections += [f"## {fn.__name__} FAILED: {e}", ""]
            add("DEGRADED", f"audit probe {fn.__name__} crashed: {e}")
    state, vlines = verdict()

    header = [f"# Estate Audit — {now.strftime('%Y-%m-%d %H:%M %Z')}",
              "_Reproducible on command (`Otto audit`). Deterministic ground-truth, no LLM._", ""]
    body = "\n".join(header + vlines + [""] + sections)

    os.makedirs(REPORTS, exist_ok=True)
    path = os.path.join(REPORTS, f"ESTATE-AUDIT-{stamp}.md")
    try:
        with open(path, "w") as f:
            f.write(body)
    except Exception as e:
        print(f"(could not write report: {e})", file=sys.stderr)

    print(body)

    if "--telegram" in sys.argv:
        broken = [m for s, m in findings if s == "BROKEN"]
        degraded = [m for s, m in findings if s == "DEGRADED"]
        tg = [f"🩺 *Estate audit* — {state}", ""]
        if broken:
            tg.append("*Broken:*")
            tg += [f"• {m.split(' — ')[0].split(' (R')[0]}" for m in broken[:6]]
        if degraded:
            tg.append("*Degraded:*")
            tg += [f"• {m.split(' — ')[0].split(' (R')[0]}" for m in degraded[:5]]
        if not broken and not degraded:
            tg.append("All subsystems healthy ✅")
        tg.append("")
        tg.append(f"Full report: `{path}`")
        print("===TELEGRAM===")
        print("\n".join(tg))
        print("===TELEGRAM===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
