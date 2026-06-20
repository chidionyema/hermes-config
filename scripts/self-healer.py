#!/usr/bin/env python3
"""Self-Healer: reads watchdog alerts and auto-fixes what it CAN — honestly.

WHAT CHANGED (Fire: the actuator was writing the field the verifier reads)
  The old fix_cron_stale() wrote `last_status="ok"` into cron/jobs.json. But BOTH the
  watchdog detector AND the alert-resolver verifier READ that same field. So a single
  heal silently (a) blinded the detector and (b) forged "probe_verified resolved" — the
  fix overwrote the evidence. That is sensor-actuator contamination: the healer was
  grading its own homework.

  The healer now writes ONLY to its own healer_state.json. It NEVER touches jobs.json.
  A cron error is "resolved" by exactly one thing: the cron actually RUNNING successfully
  again (the cron runner writes last_status + a fresh last_run_at; the resolver requires
  that fresh real run — see alert-resolver._v_cron_error). The healer cannot fake it.

  Escalation ratchet: after K real heal attempts with no genuine recovery, the healer
  STOPS trying and sets needs_human — a stuck condition surfaces to the human instead of
  being silently "healed" forever. needs_human auto-clears when the cron next runs ok.

  All subprocess calls go through hermes_subprocess.run_bounded (no orphan factories).
"""
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hermes_subprocess import sh, run_bounded  # noqa: E402  orphan-safe subprocess
from hermes_gateway import gateway_liveness     # noqa: E402  load-immune liveness

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
AUDIT_LOG = HERMES_HOME / "logs" / "audit" / "decision-trail.jsonl"
HEALER_STATE = HERMES_HOME / "logs" / "alerts" / "healer-state.json"

# After this many heal attempts with no real recovery, stop healing and escalate.
HEAL_MAX_K = int(os.environ.get("HERMES_HEAL_MAX_K", "3"))
# A genuine recovery counts only if the cron ran within this window (fresh real run).
HEAL_FRESH_HOURS = float(os.environ.get("HERMES_HEAL_FRESH_HOURS", "1"))


def iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


# ── healer's OWN state (never jobs.json) ──────────────────────────────────────
def _load_healer_state():
    if HEALER_STATE.exists():
        try:
            return json.loads(HEALER_STATE.read_text())
        except (OSError, json.JSONDecodeError):
            pass
    return {"jobs": {}}


def _save_healer_state(state):
    HEALER_STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = HEALER_STATE.parent / f".healer-{os.getpid()}.tmp"
    tmp.write_text(json.dumps(state, indent=2))
    os.replace(tmp, HEALER_STATE)


def _load_jobs():
    jp = HERMES_HOME / "cron" / "jobs.json"
    if not jp.exists():
        return []
    try:
        return json.loads(jp.read_text()).get("jobs", [])
    except (OSError, json.JSONDecodeError):
        return []


def _job_recovered(name) -> bool:
    """True iff the named cron has genuinely recovered: not erroring AND it actually
    ran (fresh last_run_at) — proof from the workload, not from the healer."""
    for j in _load_jobs():
        if j.get("name") == name or name in j.get("name", ""):
            if j.get("last_status") == "error":
                return False
            last = _parse_iso(j.get("last_run_at"))
            if not last:
                return False
            hours = (datetime.now(timezone.utc) - last).total_seconds() / 3600
            return hours <= HEAL_FRESH_HOURS
    return False


def reconcile(state):
    """Auto-clear heal counters / needs_human for any job that genuinely recovered.
    Without this, needs_human would leak forever on conditions that healed themselves."""
    for name in list(state["jobs"].keys()):
        if _job_recovered(name):
            state["jobs"].pop(name, None)
    return state


def record_heal_attempt(name, state):
    """Track a heal attempt in healer_state ONLY. Returns (should_escalate, attempts).
    Never writes jobs.json — the field the verifier reads stays owned by the cron runner."""
    j = state["jobs"].setdefault(
        name, {"heal_count": 0, "first_heal_at": iso_now(), "last_heal_at": None, "needs_human": False})
    j["heal_count"] += 1
    j["last_heal_at"] = iso_now()
    if j["heal_count"] >= HEAL_MAX_K:
        j["needs_human"] = True
    return j["needs_human"], j["heal_count"]


def fix_gateway():
    """Restart the gateway ONLY if it is GENUINELY down (load-immune liveness, not ps).
    An UNKNOWN reading (None) never triggers a restart — we don't act on uncertainty."""
    if gateway_liveness() is not False:   # True=up or None=unknown -> do nothing
        return False
    r = run_bounded("hermes gateway run --replace", timeout=30)
    return r.ok


def fix_policy_never_fired(pid):
    policy_path = HERMES_HOME / "policies" / f"{pid}.json"
    archive_dir = HERMES_HOME / "policies" / "archived"
    if not policy_path.exists():
        return False
    with open(policy_path) as f:
        p = json.load(f)
    p["status"] = "archived"
    p["archived_at"] = iso_now()
    archive_dir.mkdir(parents=True, exist_ok=True)
    with open(archive_dir / f"{pid}.json", "w") as f:
        json.dump(p, f, indent=2)
    policy_path.unlink()
    return True


def log_fix(action, detail, outcome="attempted"):
    entry = {
        "timestamp": iso_now(),
        "decision_type": "auto_heal",
        "description": f"{action}: {detail}",
        "rationale": "auto-remediation from watchdog alert",
        "outcome": outcome,
        "source": "self-healer",
    }
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _name_after_prefix(alert, tail):
    parts = alert.split(": ", 1)
    if len(parts) > 1:
        return parts[1].split(tail)[0]
    return ""


def heal(alerts):
    """Try to fix each alert HONESTLY. Cron errors are tracked + escalated, never faked.
    Returns list of human-readable actions taken."""
    state = reconcile(_load_healer_state())
    fixes = []

    def track_cron(name, label):
        if not name:
            return
        escalate, attempts = record_heal_attempt(name, state)
        if escalate:
            fixes.append(f"ESCALATE {name}: unhealed after {attempts} attempts — needs human")
            log_fix("escalate", f"{name} unhealed x{attempts}", outcome="needs_human")
        else:
            fixes.append(f"TRACKED {label} for {name} (attempt {attempts}; awaiting a real run)")
            log_fix("cron_track", f"{name} attempt {attempts}")

    for alert in alerts:
        if alert.startswith("CRON_STALE"):
            track_cron(_name_after_prefix(alert, " not run"), "stale")
        elif alert.startswith(("CRON_ERROR", "CRON_PARSE")):
            track_cron(_name_after_prefix(alert, " errored"), "error")
        elif alert.startswith("IDLE_ERROR"):
            track_cron("idle-continuous-learning", "idle error")
        elif alert.startswith(("GATEWAY_DOWN", "GATEWAY_RESTART_LOOP")):
            escalate, attempts = record_heal_attempt("gateway", state)
            if escalate:
                fixes.append(f"ESCALATE gateway: restart loop unbroken after {attempts} attempts — needs human")
                log_fix("escalate", f"gateway unhealed x{attempts}", outcome="needs_human")
            elif fix_gateway():
                fixes.append("RESTARTED gateway (was genuinely down)")
                log_fix("gateway_restart", "process was down", outcome="fixed")
            else:
                fixes.append(f"gateway not genuinely down — no restart (attempt {attempts})")
        elif alert.startswith("GATEWAY_IDLE"):
            pass
        elif alert.startswith("POLICY_NEVER_FIRED"):
            pid = _name_after_prefix(alert, " has")
            if pid and fix_policy_never_fired(pid):
                fixes.append(f"ARCHIVED {pid} (never fired)")
                log_fix("policy_archive", pid, outcome="fixed")

    _save_healer_state(state)
    return fixes


if __name__ == "__main__":
    alerts = sys.argv[1:] if len(sys.argv) > 1 else \
        [l.strip() for l in sys.stdin if l.strip()]
    fixes = heal(alerts)
    if fixes:
        print(f"🔧 Self-healer processed {len(fixes)} item(s):")
        for f in fixes:
            print(f"   • {f}")
    else:
        print("Nothing to heal")
