# Cron Silent-Stretch Detection

**Class of bug:** A cron job has not actually run for N+ cadences, but the watchdog reports it as healthy. The cron ticker has been "fast-forwarding" the schedule, and the watchdog's check uses a field the ticker updates.

**Symptoms:**
- A job with `last_status: "ok"` and `last_run_at` days-to-weeks old
- `next_run_at` in the future (looks "fresh")
- Watchdog reports 0 alerts
- The job IS in the cron ticker's run-queue — it's just not actually executing

**When it was discovered:** 2026-07-06 → 2026-07-08 → 2026-07-10. Recurred across 3 audits before the structural fix landed.

## Structural Root Cause

The cron ticker (`~/.hermes/cron/jobs.json` `next_run_at` write path) advances `next_run_at` to "next scheduled time" on every fast-forward, **without preserving a trail of the fast-forwards**. So `next_run_at` always looks fresh, even when the job hasn't actually run for weeks.

The naive watchdog check uses `next_run_at` as its staleness signal — which the ticker keeps "current" on every fast-forward. The check is **structurally blind to the stretch**.

## Why Earlier Fixes Missed the Real Layer

Two consecutive attempts prescribed the wrong layer:

- **07-06 audit:** "the cron ticker fast-forward updates next_run_at before the watchdog reads it" — prescribed a watchdog-side fix to track fast-forwards across runs.
- **07-08 audit:** implemented `check_cron_silent_stretch()` in `watchdog.py`. Used a per-job `fast_forward_streaks` state dict. **Still missed historical accumulation** because it only incremented the streak when `next_run_at` *changed* between consecutive watchdog runs. After the ticker advanced `next_run_at` once (to the next scheduled time), subsequent watchdog runs saw `schedule_at == next_raw` and recorded no change. So a job silent for 19 days had `streak=0`.

**The structural lesson:** Don't try to detect accumulation by diffing between watchdog runs. **Compute the drift directly from the current `jobs.json`** — it has all the data needed (last_run_at, next_run_at, schedule). The watchdog doesn't need a streak state to see a 19-day-old last_run.

## Layer-Verification Diagnostic (the 3-question test)

Before patching anything, answer these. The 2026-07-10 audit ran this diagnostic and the answers pointed at the detector, not the ticker.

1. **What field does the buggy check consume?** If it reads `next_run_at` and the ticker updates `next_run_at` on every fast-forward, no amount of watchdog logic can detect historical accumulation — the data is already stale before the check runs. → The fix lives in the **detector logic**, not the ticker.

2. **Is the bug visible to the check?** Run the check with a known-bad input (a job with `last_run_at` 19 days old, `last_status: "ok"`, weekly cadence). If the check passes, the check is wrong, not the data. → The detector was wrong.

3. **Can you construct a one-line test that proves the layer is wrong?** For silent-stretch: `int((now - last_run_at) / cadence_h)` should be ≥3 for a job silent 19 days on weekly cadence. If the detector returns 0 for that input, the layer is wrong.

## The Working Fix (2026-07-10)

Replace the streak-tracker with a direct drift computation. Patch in `~/.hermes/scripts/watchdog.py`:

```python
# Cadence inference — required for the drift calculation.
_CADENCE_HOURS = {
    "*/5 * * * *": 5/60, "*/10 * * * *": 10/60, "*/15 * * * *": 15/60,
    "*/30 * * * *": 0.5, "0 * * * *": 1, "1-59/5 * * * *": 5/60,
    "0 0 * * *": 24, "0 6 * * *": 24, "0 8 * * *": 24, "0 9 * * *": 24,
    "0 18 * * *": 24, "0 0 * * 0": 168, "0 0 * * 1": 168,
}

def _infer_cadence_hours(j):
    sched = j.get("schedule") or {}
    expr = sched.get("expr") if isinstance(sched, dict) else None
    display = j.get("schedule_display") or ""
    if expr and expr in _CADENCE_HOURS:
        return _CADENCE_HOURS[expr]
    if display.startswith("every "):
        try:
            n = int(display.split()[1].rstrip("m"))
            return n / 60.0
        except (IndexError, ValueError):
            return None
    return None

def check_cron_silent_stretch(state, jobs):
    # Only check ENABLED jobs — disabled jobs are intentionally silent.
    # Threshold default 2 (one full silence cycle), env override: HERMES_CRON_SILENT_STRETCH
    threshold = int(os.environ.get("HERMES_CRON_SILENT_STRETCH", "2"))
    alerts = []
    now = datetime.now(timezone.utc)
    for j in jobs:
        if not j.get("enabled", False):
            continue
        last_raw = j.get("last_run_at")
        next_raw = j.get("next_run_at")
        if not last_raw or not next_raw:
            continue
        cadence_h = _infer_cadence_hours(j)
        if cadence_h is None or cadence_h <= 0:
            continue
        try:
            last_dt = datetime.fromisoformat(last_raw.replace("Z", "+00:00"))
            nxt_dt = datetime.fromisoformat(next_raw.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        # Primary: drift from elapsed wall-clock time.
        # Grace is 10% of cadence (or 1 minute, whichever is larger) to absorb
        # sub-cadence fractional drift in last_run_at timestamps.
        elapsed_h = (now - last_dt).total_seconds() / 3600.0
        grace_h = max(cadence_h * 0.10, 1.0 / 60.0)
        drift = max(0, int((elapsed_h + grace_h) / cadence_h)) if elapsed_h > 0 else 0
        # Backstop: if next_run_at is in the past and last_run_at hasn't moved,
        # the ticker has clearly skipped at least one schedule.
        backstop_drift = 0
        if nxt_dt < now and last_dt < now:
            backstop_drift = max(0, int((now - nxt_dt).total_seconds() / 3600.0 / cadence_h) + 1)
        if max(drift, backstop_drift) >= threshold:
            alerts.append(
                f"CRON_SILENT_STRETCH: {j['name']} missed {max(drift, backstop_drift)} "
                f"consecutive schedules (last_run_at stuck at {last_raw[:19]}, cadence={cadence_h}h)"
            )
    return alerts
```

**Why this works when the streak approach didn't:** the streak approach depends on the cron ticker producing observable changes between watchdog runs. The drift approach depends only on `last_run_at`, `next_run_at`, and the cadence — all of which are present in `jobs.json` at every watchdog run. Stateless w.r.t. watchdog frequency, immune to ticker race conditions.

**Why drift ≠ backstop:** drift measures "how many schedules fell between last_run and now." Backstop measures "how many schedules have we already missed past next_run_at." The backstop catches jobs where the ticker has been skipping past the next_run window (typical silent-stretch case) even if elapsed_h is small. Taking `max(drift, backstop)` covers both.

## Inline Verification Recipe (per SKILL.md item 8)

Don't wait for the bug condition to fire naturally. Simulate it inline:

```python
import sys
sys.path.insert(0, '/Users/chidionyema/.hermes/scripts')
from watchdog import check_cron_silent_stretch, _jobs

# Fresh state — first watchdog run after fix
state = {'fast_forward_streaks': {}}
alerts = check_cron_silent_stretch(state, _jobs())
print(f'alerts: {len(alerts)}')
for a in alerts:
    print(f'  • {a}')

# Sanity check: false positives on healthy jobs
import datetime
for j in _jobs():
    if not j.get('enabled') or j.get('last_status') != 'ok':
        continue
    from watchdog import _infer_cadence_hours
    c = _infer_cadence_hours(j)
    if not c: continue
    last_dt = datetime.datetime.fromisoformat(j['last_run_at'])
    elapsed = (datetime.datetime.now(datetime.timezone.utc) - last_dt).total_seconds()/3600
    if elapsed < c * 1.5:  # less than 1.5x cadence = healthy
        if any(j['name'] in a for a in alerts):
            print(f'  ❌ FALSE POSITIVE: {j["name"]}')
```

**Expected result (2026-07-10 production data):**
- 5 real alerts fired (1 weekly silent 19d, 4 jobs stuck 4-5h on 15-30m cadence)
- 0 false positives on healthy jobs
- All 5 fingerprints appear in `~/.hermes/logs/alerts/watchdog-state.json` with `first_seen: 2026-07-10T12:02:31Z`

## Generalization: The Pattern Applies to Other Stateful Watchdog Checks

Any watchdog check that derives "is X broken?" from a state field that another process updates is susceptible to the silent-stretch class of bug. The diagnostic question is always: **does the field the check reads get updated by a process that runs faster or differently than the check?**

Examples in the same class:
- A check that uses `last_heartbeat` when the daemon updates `last_heartbeat` even on partial failures → misses real outages.
- A check that uses `git_dirty_count` when the autosave process resets it to 0 between checks → misses drift accumulation.
- A check that uses `circuit_breaker_state` when the breaker self-resets on retry → misses repeated trips.

For all of these: **don't try to detect accumulation by diffing between runs. Compute the drift directly from the underlying source of truth.**

## Carry-Over Tracking

| Audit | Finding | Status |
|---|---|---|
| 07-02 | First silent-stretch detection prescribed (wrong layer) | superseded |
| 07-06 | Re-diagnosed, prescribed watchdog fix | superseded |
| 07-08 | Implemented detector with streak state (broke — blind to accumulation) | superseded |
| 07-10 | Re-architected with direct drift computation | **fixed, verified inline** |

This is the 4th audit to touch this class. If a 5th audit prescribes "fix the cron ticker" without running the 3-question layer-verification test, escalate the same way: AUTO-EXECUTE the detector-side fix.
