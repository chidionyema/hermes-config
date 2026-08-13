"""Regression proof for the 2026-08-11→13 false CRON_SILENT_STRETCH page.

The host slept ~46h on Low Power Sleep at 0% battery (`pmset -g log`: "Entering Sleep
state due to 'Low Power Sleep' ... Using Batt (Charge:0%)" 08-11 09:06 →
"Wake from Standby ... EC.ACAttach" 08-13 07:11). The gateway never died (pid 26654's
lstart predated the sleep). On wake, every `catch_up:true` job re-fired at 07:12:xx —
but watchdog.py's check_cron_silent_stretch paged at 07:11:58, 37s BEFORE the catch-up
run, because it derives drift purely from wall-clock `now - last_run_at` with zero
awareness of host sleep. estate_watchdog.py:45 already carried this guard; watchdog.py
did not.

This asserts the guard SUPPRESSES the sleep artifact without BLINDING the detector:
  1. gap detected + host corroborated as slept (boot id + gateway ident unchanged)
     -> _wake_grace True, and a 46h-stale 24h-cadence job raises NO alert.
  2. once the clock advances past WAKE_GRACE_S with last_run_at STILL stale
     -> _wake_grace False, and the same job DOES alert (detector still has teeth).
  3. a gap where the gateway pid/start CHANGED (crash+restart, not sleep) -> no grace.
Run: /usr/local/bin/python3 test_watchdog_wake_grace.py
"""
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import watchdog as W  # noqa: E402

hard = False
now_utc = datetime.now(timezone.utc)

# The detector now has a SECOND, permanent layer beside this time-boxed grace: an
# awake-clamp built from `pmset -g log` (watchdog._awake_since). That clamp reads the REAL
# host wake time, so a synthetic "stale for 46h" job is unfalsifiable while the real host
# woke 40 minutes ago — it is correctly not provably silent. Every assertion below about
# the detector HAVING TEETH must therefore pin the simulated wake explicitly, or it tests
# nothing but today's uptime. Section 7 pins the opposite direction.
def set_awake(dt):
    W._AWAKE_SINCE_CACHE.clear()
    W._AWAKE_SINCE_CACHE.append(dt)


LONG_AWAKE = now_utc - timedelta(days=30)   # host up for a month: no suspend excuse
set_awake(LONG_AWAKE)

# One 24h-cadence job whose last_run_at is 46h old — the exact incident shape.
JOBS = [{
    "id": "4fb05d17267d", "name": "daily-self-reflection", "enabled": True,
    "schedule": {"expr": "0 18 * * *"}, "schedule_display": "daily at 18:00",
    "last_run_at": (now_utc - timedelta(hours=46)).isoformat(),
    "next_run_at": (now_utc - timedelta(hours=22)).isoformat(),
}]

# Sanity: without the guard this job is unambiguously alerting. If this ever goes quiet
# the rest of the test proves nothing.
base = W.check_cron_silent_stretch({}, JOBS, in_wake_grace=False)
if base and base[0].startswith("CRON_SILENT_STRETCH: daily-self-reflection"):
    print(f"PASS  precondition: detector fires on the stale job -> {base[0][:70]}...")
else:
    print(f"FAIL  precondition: expected a CRON_SILENT_STRETCH, got {base!r}"); hard = True

T0 = 1_000_000.0          # fake clock origin
GAP = 46 * 3600           # the real sleep duration

# ── 1. under grace: watchdog_last_run 46h stale, boot id + gateway ident UNCHANGED ──
state = {
    "watchdog_last_run": T0 - GAP,
    "watchdog_boot_id": W._boot_id(),          # same host, no reboot
    "watchdog_gateway_ident": W._gateway_ident(),  # same gateway process
}
g1 = W._wake_grace(state, now=T0)
a1 = W.check_cron_silent_stretch(state, JOBS, in_wake_grace=g1)
if g1 and a1 == []:
    print(f"PASS  in grace (gap={state.get('watchdog_wake_gap_s')}s): suppressed, alerts={a1}")
else:
    print(f"FAIL  in grace: _wake_grace={g1} alerts={a1!r}"); hard = True

if state.get("watchdog_last_run") == T0 and state.get("watchdog_wake_at") == T0:
    print("PASS  state persisted: watchdog_last_run and watchdog_wake_at both stamped at T0")
else:
    print(f"FAIL  state not stamped: {state.get('watchdog_last_run')=} "
          f"{state.get('watchdog_wake_at')=}"); hard = True

# The suppressed tick must not leave a phantom streak behind.
streak = state.get("fast_forward_streaks", {}).get("4fb05d17267d", {})
if streak.get("streak") == 0 and streak.get("run_at") == JOBS[0]["last_run_at"]:
    print("PASS  baseline re-set during grace (streak=0, run_at rebaselined) — no phantom")
else:
    print(f"FAIL  phantom streak left behind: {streak!r}"); hard = True

# ── 2. mid-grace catch-up tick (small gap) must STILL be suppressed ──────────────
g_mid = W._wake_grace(state, now=T0 + 300)
if g_mid:
    print("PASS  grace anchored to wake_at, survives the next catch-up tick (+300s)")
else:
    print("FAIL  grace evaporated on the following catch-up tick"); hard = True

# ── 3. past WAKE_GRACE_S with last_run_at still stale: the alert MUST fire ───────
T2 = T0 + W.WAKE_GRACE_S + 60
g2 = W._wake_grace(state, now=T2)
a2 = W.check_cron_silent_stretch(state, JOBS, in_wake_grace=g2)
if (not g2) and a2 and a2[0].startswith("CRON_SILENT_STRETCH: daily-self-reflection"):
    print(f"PASS  past grace (+{int(T2 - T0)}s): detector NOT blinded -> {a2[0][:70]}...")
else:
    print(f"FAIL  past grace: _wake_grace={g2} alerts={a2!r}"); hard = True

# ── 4. gap caused by a gateway crash+restart, NOT sleep: no grace ────────────────
crashed = {
    "watchdog_last_run": T0 - GAP,
    "watchdog_boot_id": W._boot_id(),
    "watchdog_gateway_ident": ["up", 111111, "Mon Aug 10 20:11:53 2026"],  # different process
}
g3 = W._wake_grace(crashed, now=T0)
a3 = W.check_cron_silent_stretch(crashed, JOBS, in_wake_grace=g3)
if (not g3) and a3:
    print("PASS  gateway restarted across the gap -> grace REFUSED, real outage still alerts")
else:
    print(f"FAIL  crash masked as sleep: _wake_grace={g3} alerts={a3!r}"); hard = True

# ── 5. host rebooted across the gap: no grace ────────────────────────────────────
rebooted = {
    "watchdog_last_run": T0 - GAP,
    "watchdog_boot_id": "{ sec = 1, usec = 0 } Thu Jan  1 01:00:01 1970",
    "watchdog_gateway_ident": W._gateway_ident(),
}
g4 = W._wake_grace(rebooted, now=T0)
if not g4:
    print("PASS  boot time changed (reboot, not sleep) -> grace REFUSED")
else:
    print(f"FAIL  reboot masked as sleep: _wake_grace={g4}"); hard = True

# ── 6. first run ever (no prior tick) must not self-grant grace ──────────────────
fresh = {}
if not W._wake_grace(fresh, now=T0):
    print("PASS  first run (no watchdog_last_run) -> no grace")
else:
    print("FAIL  first run granted itself grace"); hard = True

# ── 7. THE ACTUAL 2026-08-11→13 FIX: past the time-boxed grace, on a host that only
#       just woke, the same 46h-stale job must STILL be silent. Section 3 proves the
#       detector keeps its teeth on a long-awake host; this proves the suspend window
#       itself is never counted as missed schedules. Without it the alert simply
#       re-fires WAKE_GRACE_S (20m) after every long sleep, which is the reported bug.
set_awake(now_utc - timedelta(minutes=40))          # woke 40m ago, like the real incident
state7 = {
    "watchdog_last_run": T0 - GAP,
    "watchdog_boot_id": W._boot_id(),
    "watchdog_gateway_ident": W._gateway_ident(),
}
W._wake_grace(state7, now=T0)                        # enter grace
g7 = W._wake_grace(state7, now=T2)                   # ...then advance past it
a7 = W.check_cron_silent_stretch(state7, JOBS, in_wake_grace=g7)
if (not g7) and a7 == []:
    print("PASS  past grace but host only awake 40m: suspend time is not missed schedules")
else:
    print(f"FAIL  false page returns after grace expires: _wake_grace={g7} alerts={a7!r}"); hard = True

# ── 8. and the phantom streak must not survive the sleep either ──────────────────
set_awake(now_utc - timedelta(minutes=40))
state8 = {"fast_forward_streaks": {"4fb05d17267d": {
    "schedule_at": "2000-01-01T00:00:00+00:00",
    "run_at": JOBS[0]["last_run_at"], "streak": 94}}}   # pre-wake, no streak_at
a8 = W.check_cron_silent_stretch(state8, JOBS, in_wake_grace=False)
s8 = state8["fast_forward_streaks"]["4fb05d17267d"]["streak"]
if a8 == [] and s8 == 0:
    print("PASS  pre-wake streak=94 drained, no alert (sticky false positive killed)")
else:
    print(f"FAIL  sticky streak survived the sleep: alerts={a8!r} streak={s8}"); hard = True

set_awake(LONG_AWAKE)
print("ALL GREEN" if not hard else "FAILURES ABOVE")
sys.exit(1 if hard else 0)
