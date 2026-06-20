#!/usr/bin/env python3
"""Deterministic proof for the resolution-disease fix (war-room root cause).

Run: python3 test_resolution_disease.py    (no pytest; pure asserts, temp HERMES_HOME)

Proves, against an isolated HERMES_HOME, the two failure modes the founder named:
  1. "letting the actuator write the field the verifier reads"
       - self-healer NEVER writes cron/jobs.json
       - a healer-forged / pre-existing 'ok' WITHOUT a fresh real run does NOT clear a
         CRON_ERROR alert (verifier returns UNKNOWN -> alert stays open)
       - a REAL run that post-dates the alert DOES clear it
       - the heal ratchet escalates to needs_human after K, then auto-clears on recovery
  2. "snapshot-as-proof"
       - GATEWAY_RESTART_LOOP has a verifier
       - it resolves only on sustained liveness with a freshness guard (stale -> UNKNOWN)
"""
import importlib.util
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(modname, filename):
    spec = importlib.util.spec_from_file_location(modname, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _set_home(td):
    """Point every already-imported module at a fresh temp HERMES_HOME."""
    home = Path(td)
    (home / "cron").mkdir(exist_ok=True)
    (home / "logs" / "alerts").mkdir(parents=True, exist_ok=True)
    os.environ["HERMES_HOME"] = str(home)
    return home


def _write_jobs(home, jobs):
    (home / "cron" / "jobs.json").write_text(json.dumps({"jobs": jobs}))


def main():
    os.environ["HERMES_HOME"] = tempfile.mkdtemp()  # safe default before imports read it
    healer = _load("selfhealer", "self-healer.py")
    resolver = _load("alertresolver", "alert-resolver.py")

    now = datetime.now(timezone.utc)
    alert_open = now - timedelta(hours=2)          # the alert opened 2h ago
    passed = []

    # ════ FIRE 1: actuator cannot forge resolution ════════════════════════════
    with tempfile.TemporaryDirectory() as td:
        home = _set_home(td)
        healer.HERMES_HOME = home
        healer.HEALER_STATE = home / "logs" / "alerts" / "healer-state.json"
        healer.AUDIT_LOG = home / "logs" / "audit" / "decision-trail.jsonl"
        resolver.HERMES_HOME = home

        # cron is erroring; the alert is open
        _write_jobs(home, [{"name": "demo", "last_status": "error",
                            "last_error": "boom", "last_run_at": _iso(alert_open - timedelta(hours=1)),
                            "enabled": True}])

        # (a) healer runs — it must NOT write jobs.json, only its own state
        jobs_before = (home / "cron" / "jobs.json").read_text()
        healer.heal(["CRON_ERROR: demo errored: boom"])
        jobs_after = (home / "cron" / "jobs.json").read_text()
        assert jobs_before == jobs_after, "healer MUST NOT touch cron/jobs.json"
        assert healer.HEALER_STATE.exists(), "healer must write its own healer-state.json"
        passed.append("healer writes healer-state.json and never touches jobs.json")

        # (b) verifier on a still-erroring job -> active (False)
        entry = {"message": "CRON_ERROR: demo errored: boom", "timestamp": _iso(alert_open)}
        assert resolver._v_cron_error(entry) is False, "still-erroring must read active"
        passed.append("still-erroring cron reads ACTIVE (False)")

        # (c) the disease: flip last_status to 'ok' but with a STALE run that predates the
        #     alert (exactly what a forged heal / pre-existing ok looks like) -> must NOT clear
        _write_jobs(home, [{"name": "demo", "last_status": "ok", "last_error": None,
                            "last_run_at": _iso(alert_open - timedelta(hours=1)), "enabled": True}])
        v = resolver._v_cron_error(entry)
        assert v is None, f"forged/stale 'ok' must read UNKNOWN (keep open), got {v!r}"
        passed.append("forged/stale 'ok' WITHOUT a fresh run -> UNKNOWN (alert stays open)")

        # (d) a REAL run that post-dates the alert -> genuinely cleared (True)
        _write_jobs(home, [{"name": "demo", "last_status": "ok", "last_error": None,
                            "last_run_at": _iso(now), "enabled": True}])
        assert resolver._v_cron_error(entry) is True, "fresh real run post-alert must clear"
        passed.append("REAL run post-dating the alert -> CLEARED (True)")

    # ════ heal ratchet: escalate after K, auto-clear on recovery ═══════════════
    with tempfile.TemporaryDirectory() as td:
        home = _set_home(td)
        healer.HERMES_HOME = home
        healer.HEALER_STATE = home / "logs" / "alerts" / "healer-state.json"
        healer.AUDIT_LOG = home / "logs" / "audit" / "decision-trail.jsonl"

        _write_jobs(home, [{"name": "demo", "last_status": "error", "last_error": "boom",
                            "last_run_at": _iso(now - timedelta(hours=5)), "enabled": True}])
        k = healer.HEAL_MAX_K
        for _ in range(k):
            healer.heal(["CRON_ERROR: demo errored: boom"])
        st = json.loads(healer.HEALER_STATE.read_text())
        assert st["jobs"]["demo"]["needs_human"] is True, f"must escalate after {k} heals"
        assert st["jobs"]["demo"]["heal_count"] >= k
        passed.append(f"heal ratchet -> needs_human after K={k} attempts")

        # recovery: a fresh real run -> reconcile drops the job entirely (needs_human clears)
        _write_jobs(home, [{"name": "demo", "last_status": "ok", "last_error": None,
                            "last_run_at": _iso(now), "enabled": True}])
        healer.heal([])  # heal() reconciles at entry
        st = json.loads(healer.HEALER_STATE.read_text())
        assert "demo" not in st["jobs"], "genuine recovery must auto-clear needs_human"
        passed.append("needs_human auto-clears on a genuine fresh run")

    # ════ FIRE 2: snapshot-as-proof — gateway sustained verifier ═══════════════
    with tempfile.TemporaryDirectory() as td:
        home = _set_home(td)
        resolver.HERMES_HOME = home
        resolver.STATE_FILE = home / "logs" / "alerts" / "watchdog-state.json"
        N = resolver.SUSTAIN_N

        assert "GATEWAY_RESTART_LOOP" in resolver.VERIFIERS, \
            "GATEWAY_RESTART_LOOP MUST have a verifier (was the coverage hole)"
        passed.append("GATEWAY_RESTART_LOOP now has a verifier")

        def write_hist(entries):
            resolver.STATE_FILE.write_text(json.dumps({"daemon_history": entries}))

        fresh = _iso(now)

        # fresh window, last N all up -> resolved (True)
        write_hist([{"ts": fresh, "state": "up"}] * (N + 1))
        assert resolver._v_gateway_sustained({}) is True, "fresh all-up -> resolved"
        passed.append("fresh + last N all-up -> RESOLVED (True)")

        # fresh window with a genuine down in the last N -> active (False)
        win = [{"ts": fresh, "state": "up"}] * N
        win[-1] = {"ts": fresh, "state": "down"}
        write_hist(win)
        assert resolver._v_gateway_sustained({}) is False, "down in window -> active"
        passed.append("fresh window with a real DOWN -> ACTIVE (False)")

        # UNKNOWN readings don't count as down: last known N are up, despite unknowns
        write_hist([{"ts": fresh, "state": "up"}] * N + [{"ts": fresh, "state": "unknown"}] * 2)
        assert resolver._v_gateway_sustained({}) is True, "unknowns must not block resolution"
        passed.append("UNKNOWN readings excluded; known N up -> RESOLVED")

        # STALE window (last reading older than freshness guard) -> UNKNOWN (None)
        stale = _iso(now - timedelta(seconds=resolver.GATEWAY_FRESH_SECONDS + 60))
        write_hist([{"ts": stale, "state": "up"}] * (N + 1))
        assert resolver._v_gateway_sustained({}) is None, \
            "stale window must read UNKNOWN (no deadlock, no false-clear)"
        passed.append("STALE window -> UNKNOWN (freshness guard holds)")

        # not enough evidence yet -> UNKNOWN
        write_hist([{"ts": fresh, "state": "up"}] * (N - 1))
        assert resolver._v_gateway_sustained({}) is None, "insufficient history -> UNKNOWN"
        passed.append("insufficient history -> UNKNOWN")

    print("RESOLUTION-DISEASE PROOF — all invariants hold:")
    for p in passed:
        print(f"  ✅ {p}")
    print(f"\n{len(passed)} checks PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
