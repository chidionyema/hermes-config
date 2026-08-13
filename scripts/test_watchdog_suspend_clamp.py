#!/usr/bin/env python3
"""Acceptance test — CRON_SILENT_STRETCH must not fire on host-suspend time.

Incident 2026-08-11 09:06 -> 2026-08-13 07:11 (46.1h 'Low Power Sleep' on a dead
battery). Job f5f63e9ff435 ('Summarize today's activity...', `0 18 * * *`) had both its
08-11 and 08-12 fires inside the sleep window and was paged as "missed 2 consecutive
schedules". The scheduler never crashed; the detector counted suspended wall-clock as
missed schedules (watchdog.py `elapsed_h = (now - last_dt)`, no host-suspend awareness).

Loads the detector FRESH FROM DISK and grades it against the LIVE jobs.json plus
synthetic controls. Exit 0 = pass, 1 = fail (with the failing assertion printed).
"""
import importlib, json, os, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
for _m in ("watchdog",):
    if _m in sys.modules:
        del sys.modules[_m]
wd = importlib.import_module("watchdog")

FAILS = []
NOW = datetime.now(timezone.utc)


def check(label, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + label + (f"  [{detail}]" if detail else ""))
    if not cond:
        FAILS.append(f"{label} :: {detail}")


def fresh_state():
    return {"fingerprints": {}, "daemon_history": []}


# ── 0. the helper itself ─────────────────────────────────────────────────────
awake = wd._awake_since()
print(f"_awake_since() -> {awake!r}   (now={NOW.isoformat()})")
check("host wake timestamp is parseable and tz-aware",
      awake is not None and awake.tzinfo is not None, str(awake))
awake_h = (NOW - awake).total_seconds() / 3600.0 if awake else None
print(f"host awake for {awake_h:.2f}h" if awake_h is not None else "awake_h unavailable")

# ── 1. THE ORIGINAL FAILURE, against the live jobs.json ──────────────────────
jobs = wd._jobs()
target = next((j for j in jobs if j.get("id") == "f5f63e9ff435"), None)
check("target job f5f63e9ff435 present in live jobs.json", target is not None)
if target:
    print(f"  live: last_run_at={target.get('last_run_at')} next_run_at={target.get('next_run_at')} "
          f"enabled={target.get('enabled')} last_status={target.get('last_status')}")

alerts = wd.check_cron_silent_stretch(fresh_state(), jobs, in_wake_grace=False)
print("live-jobs alerts:", json.dumps(alerts, indent=2))
check("NO CRON_SILENT_STRETCH for the incident job", not any("f5f63e9ff435" in a or
      "Summarize today's activity" in a for a in alerts), "; ".join(alerts))
check("NO CRON_SILENT_STRETCH at all on live jobs (host awake %.2fh)" % (awake_h or -1),
      alerts == [], "; ".join(alerts))

# ── 2. sticky streak must be cleared, not preserved ──────────────────────────
st = fresh_state()
st["fast_forward_streaks"] = {j.get("id"): {"schedule_at": j.get("next_run_at"),
                                            "run_at": j.get("last_run_at"),
                                            "streak": 7} for j in jobs if j.get("id")}
sticky_alerts = wd.check_cron_silent_stretch(st, jobs, in_wake_grace=False)
print("alerts raised from the seeded pre-wake streaks:", sticky_alerts)
leftover = {k: v["streak"] for k, v in st["fast_forward_streaks"].items() if v.get("streak")}
check("phantom streaks reset to 0 (no sticky false positive)", leftover == {}, str(leftover))
check("pre-wake streaks raise no alert", sticky_alerts == [], str(sticky_alerts))

# ── 2b. a streak accrued AFTER the wake must still page (signal not neutered) ─
st2 = fresh_state()
_SLR = (NOW - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
streak_job = [{
    "id": "SYNTH-STREAK", "name": "synthetic-post-wake-streak", "enabled": True,
    "schedule": {"kind": "cron", "expr": "*/5 * * * *"}, "schedule_display": "*/5 * * * *",
    "last_run_at": _SLR,
    "next_run_at": (NOW + timedelta(minutes=4)).isoformat().replace("+00:00", "Z"),
    "last_status": "ok",
}]
# run_at unchanged (job never fired) + schedule_at fast-forwarded = the ticker skipping it.
st2["fast_forward_streaks"] = {"SYNTH-STREAK": {
    "schedule_at": "2000-01-01T00:00:00+00:00", "run_at": _SLR,
    "streak": 5, "streak_at": NOW.isoformat()}}
sa = wd.check_cron_silent_stretch(st2, streak_job, in_wake_grace=False)
check("post-wake streak evidence STILL pages", any("synthetic-post-wake-streak" in a for a in sa),
      str(sa))

# ── 3. POSITIVE CONTROL: a genuinely stale job must still page ───────────────
# 5-minute cadence, last run 30m ago, host awake > cadence+grace => really silent.
stale = [{
    "id": "SYNTH-STALE", "name": "synthetic-genuinely-stale", "enabled": True,
    "schedule": {"kind": "cron", "expr": "*/5 * * * *"}, "schedule_display": "*/5 * * * *",
    "last_run_at": (NOW - timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
    "next_run_at": (NOW - timedelta(minutes=25)).isoformat().replace("+00:00", "Z"),
    "last_status": "ok",
}]
pos = wd.check_cron_silent_stretch(fresh_state(), stale, in_wake_grace=False)
print("positive-control alerts:", pos)
check("detector STILL FIRES on a genuinely stale job", any("synthetic-genuinely-stale" in a for a in pos),
      str(pos))

# ── 4. NEGATIVE CONTROL: same cadence, ran a minute ago ──────────────────────
healthy = [dict(stale[0], id="SYNTH-OK", name="synthetic-healthy",
                last_run_at=(NOW - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
                next_run_at=(NOW + timedelta(minutes=4)).isoformat().replace("+00:00", "Z"))]
neg = wd.check_cron_silent_stretch(fresh_state(), healthy, in_wake_grace=False)
check("no alert for a job that just ran", neg == [], str(neg))

# ── 5. SUSPEND SIMULATION: daily job whose only misses are inside the sleep ──
# Exactly the incident shape, built from scratch so it does not depend on jobs.json.
sim = [{
    "id": "SYNTH-SLEPT", "name": "synthetic-daily-across-sleep", "enabled": True,
    "schedule": {"kind": "cron", "expr": "0 18 * * *"}, "schedule_display": "0 18 * * *",
    "last_run_at": "2026-08-10T18:00:17.891184+01:00",
    "next_run_at": "2026-08-13T18:00:00+01:00", "last_status": "ok",
}]
sim_alerts = wd.check_cron_silent_stretch(fresh_state(), sim, in_wake_grace=False)
check("daily job whose misses fall inside the 46h sleep does not page", sim_alerts == [],
      str(sim_alerts))

# ── 6. sibling detector: CRON_STALE must not fire from suspend time either ───
health = wd.check_cron_health(in_wake_grace=False)
stale_alerts = [a for a in health if a.startswith("CRON_STALE")]
print("check_cron_health CRON_STALE:", stale_alerts)
check("no CRON_STALE from suspended wall-clock", stale_alerts == [], str(stale_alerts))

# ── 7. fallback safety: helper unavailable => old behaviour, never silence ───
_orig = wd._AWAKE_SINCE_CACHE[:]
wd._AWAKE_SINCE_CACHE.clear()
wd._AWAKE_SINCE_CACHE.append(None)          # simulate non-Darwin / parse failure
fb = wd.check_cron_silent_stretch(fresh_state(), stale, in_wake_grace=False)
check("with _awake_since()=None the detector still fires (fails OPEN, not silent)",
      any("synthetic-genuinely-stale" in a for a in fb), str(fb))
wd._AWAKE_SINCE_CACHE.clear()
wd._AWAKE_SINCE_CACHE.extend(_orig)

print("\n" + ("ACCEPTANCE: PASS" if not FAILS else "ACCEPTANCE: FAIL"))
for f in FAILS:
    print("  !", f)
sys.exit(0 if not FAILS else 1)
