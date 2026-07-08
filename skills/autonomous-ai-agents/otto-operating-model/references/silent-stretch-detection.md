# Silent-Stretch Detection — Cron Silent Failure Pattern

**Discovered:** 2026-07-06 daily-strategist-audit
**Updated:** 2026-07-08 (hybrid approach applied)
**Status:** Observable-layer detector live; structural cron-ticker patch pending
**Owner:** watchdog.py (observable) + cron ticker (structural)

## The Pattern

A cron job can go hours-to-days without actually executing, while reporting `last_status: ok`. This is the **silent-stretch** pattern. Three preconditions:

1. The cron ticker is behind schedule (CPU contention, IO wait, scheduler stalls, gateway wake window).
2. The ticker fast-forwards missed jobs: instead of firing them late, it advances `next_run_at` to the next slot and marks the missed run as "skipped."
3. The watchdog's CRON_STALE check uses `next_run_at` as its data source, so the watchdog sees a "fresh" schedule even though the job never actually ran.

The net effect: a daily job that should run at 8am can go 3+ days without firing, and every layer of the system (cron, watchdog, audit) reports green.

## Evidence (2026-07-06)

```
$ grep 'missed its scheduled time' ~/.hermes/logs/agent.log
2026-07-05 23:38:19 cron.jobs: Job 'queue-curator' missed its scheduled time (..., grace=150s). Fast-forwarding to next run: ...
2026-07-06 01:16:07 cron.jobs: Job 'queue-curator' missed its scheduled time (..., grace=150s). Fast-forwarding to next run: ...
2026-07-06 03:44:09 cron.jobs: Job 'queue-curator' missed its scheduled time (..., grace=150s). Fast-forwarding to next run: ...
2026-07-06 05:45:07 cron.jobs: Job 'queue-curator' missed its scheduled time (..., grace=150s). Fast-forwarding to next run: ...
2026-07-06 08:51:53 cron.jobs: Job 'queue-curator' missed its scheduled time (..., grace=150s). Fast-forwarding to next run: ...

$ jq -r '.jobs[] | select(.last_status == "ok") | "\(.name) | last=\(.last_run_at)"' jobs.json | sort -k 3
Run health check on all projects: check | last=2026-06-18T09:42:40  ← 18 days silent
otto-dispatch                              | last=2026-06-20T15:21:30  ← 16 days silent
otto-improvement-pulse                     | last=2026-06-21T00:00:07  ← 15 days silent
Run lux verify on all projects with spec  | last=2026-06-21T00:00:07  ← 15 days silent
daily-strategist-audit                     | last=2026-07-03T08:09:35  ← 3 days silent
estate-inventory-audit                     | last=2026-07-04T06:52:20  ← 2 days silent
morning-briefing                           | last=2026-07-05T09:25:10  ← 1 day silent
```

Five cron jobs are 2+ weeks silent, all reporting `last_status: ok`. The watchdog is silent. The 8am audit (this very report) is the FIRST signal that the silent stretch was a problem.

## Layer-Confusion Trap

A naive auto-fix would patch the watchdog. **This is the wrong layer.** The watchdog's CRON_STALE check is structurally blind to silent-stretch because the data it reads is being fast-forwarded by the cron ticker.

Three diagnostic checks to confirm the layer is right:

1. **What field does the check consume?** `CRON_STALE` reads `next_run_at`. The cron ticker writes `next_run_at` on every fast-forward. Therefore the check sees a "fresh" schedule even when no run happened. **Layer is wrong.**

2. **Is the bug visible to the check with a known-bad input?** Construct: cron job with `last_run_at = 7 days ago`, `next_run_at = now`. The check should fire. It does not. **Layer is wrong.**

3. **Can a one-line test prove it?** `python3 -c "from datetime import datetime, timezone; print(datetime.fromisoformat('2026-07-06T08:00:00+00:00') > datetime.now(timezone.utc))"` — yes, trivial. **Layer is wrong, the test is fast.**

When all three checks say "wrong layer," do not patch the watchdog. The fix lives in the cron-ticker's `next_run_at` write path.

## The Right Fix — APPLIED 2026-07-08 (Hybrid Approach)

The 2026-07-06 audit correctly identified "patch the watchdog CRON_STALE check" as the wrong layer (next_run_at gets fast-forwarded, masking the gap). The 2026-07-08 audit found a **third option** beyond the binary in the layer-confusion trap:

**Option 3: Detect from the observable layer.** The watchdog cannot see fast-forward events directly, but it CAN detect them indirectly by comparing the schedule's `next_run_at` against `last_run_at` across consecutive watchdog runs. If `next_run_at` keeps advancing while `last_run_at` stays frozen, the ticker is fast-forwarding without firing. The watchdog stores per-job state, so it can track this as a streak.

**Implementation** (in `~/.hermes/scripts/watchdog.py`, applied 2026-07-08 audit):

```python
def check_cron_silent_stretch(state, jobs):
    """Detect cron jobs whose schedule keeps advancing without firing.
    The cron ticker fast-forwards on missed schedules (correct in isolation),
    but 3+ consecutive fast-forwards for the same job is structurally silent."""
    fast_forward_state = state.setdefault("fast_forward_streaks", {})
    alerts = []
    for j in jobs:
        jid, name = j.get("id", ""), j.get("name", "")
        next_raw, last_raw = j.get("next_run_at"), j.get("last_run_at")
        if not (next_raw and last_raw): continue
        rec = fast_forward_state.setdefault(jid, {"schedule_at": next_raw, "run_at": last_raw, "streak": 0})
        if rec["schedule_at"] == next_raw and rec["run_at"] == last_raw:
            pass  # No change — not a new fast-forward event
        elif rec["schedule_at"] != next_raw and rec["run_at"] == last_raw:
            rec["streak"] += 1; rec["schedule_at"] = next_raw; rec["run_at"] = last_raw
        elif rec["run_at"] != last_raw:
            rec["streak"] = 0; rec["schedule_at"] = next_raw; rec["run_at"] = last_raw
        if rec["streak"] >= 3:
            alerts.append(f"CRON_SILENT_STRETCH: {name} missed {rec['streak']} consecutive schedules (last_run_at stuck at {last_raw[:19]})")
    return alerts
```

**Threshold** (env-tunable): `HERMES_CRON_SILENT_STRETCH` (default `3`). State file key: `fast_forward_streaks[<job_id>].streak`.

**Verification pattern (reusable for any new watchdog check):** Rather than wait for the silent job to fire, simulate it: manipulate `watchdog-state.json` to set `schedule_at` to a stale value and `streak=2`, call `check_cron_silent_stretch(state, jobs)` once, confirm alert fires; clean up the test artifact.

**Tradeoff vs. Option 1 (cron ticker source patch):** Observable-layer detection has 1 run-cycle of latency — the watchdog fires after the silent stretch has already happened, not before. It catches silent-stretch but doesn't prevent it. The cron-ticker fix would prevent fast-forwards from happening in the first place. For the current state of the system, observable-layer is the right tradeoff: cron-ticker source is opaque, watchdog is the only observable surface, and a 1-cycle lag is acceptable.

## Diagnostic Command (one-liner)

```bash
jq -r '.jobs[] | select(.schedule.kind == "cron" and .enabled == true and .last_run_at != null) | "\(.name)|\(.last_run_at)|\(.schedule.expr)"' ~/.hermes/cron/jobs.json | \
  python3 -c "
import sys, datetime
intervals = {'0 8 * * *': 26, '0 9 * * *': 26, '0 18 * * *': 26, '0 6 * * *': 26, '0 * * * *': 2, '0 0 * * 0': 7*24+2}
now = datetime.datetime.now(datetime.timezone.utc)
for line in sys.stdin:
    name, last, expr = line.strip().split('|')
    last_dt = datetime.datetime.fromisoformat(last.replace('Z', '+00:00'))
    age_h = (now - last_dt).total_seconds() / 3600
    threshold = intervals.get(expr, 26)
    if age_h > threshold:
        print(f'⚠️  SILENT-STRETCH: {name} | {age_h:.0f}h old | expr={expr} | threshold={threshold}h')
"
```

## Related Findings (same root cause class)

- **9-day audit gap (06-24 → 07-01):** gateway was down. Watchdog silent. Same "every layer reports green" symptom.
- **DeepSeek billing exhaustion (07-06 → ongoing):** model 402s, cron job reports `last_status: error`, audit silently fails to write its report. **Layer-confusion trap here too:** the CREDITS_ERROR classifier works at the watchdog layer (it detects the 402), but the audit job itself 402s before it can read the watchdog log. The fix is upstream — provider billing — not in the watchdog.
- **Reflect-on-correction.py spam (06-20):** script emits hardcoded templated text every 30m regardless of correction events. Same class: monitoring layer trusts a stale data source.

The root cause class is **"monitoring layer trusts data written by the failing layer."** A structural enforcer for this class: every watchdog check that reads a state field must also include a sanity check against the **raw event log** for the same entity, with at-least-one-check-per-day cadence. If the raw log is empty but the state field is "fresh," the silence is a silent stretch.

## Field-key distinction table (cron jobs.json)

| Field | Volatility | Source | Trustworthiness |
|---|---|---|---|
| `last_run_at` | Durable — only updated on actual run | Cron ticker on job completion | **High** — this is the ground truth for "did it run" |
| `last_status` | Durable | Cron ticker | **Medium** — survives fast-forwards but doesn't reflect missed runs |
| `next_run_at` | Volatile — updated on EVERY fast-forward | Cron ticker | **Low** — always looks fresh even when no run happened |
| `enabled` | Manual | User config | High |
| `schedule.expr` | Manual | User config | High |

**Diagnostic rule:** any check that compares `next_run_at` against `now` is structurally blind to silent-stretch. Use `last_run_at` against the schedule's expected interval instead.

## Carry-Over (Updated 2026-07-08)

This finding was re-prescribed in audits 07-02, 07-03, 07-06, 07-08. As of 07-08:
- ✅ Watchdog-side `CRON_SILENT_STRETCH` check **APPLIED** (observable layer, Option 3). Verified by simulation in the same audit.
- ⏸️ Cron-ticker source patch (Option 1, the structural fix) still pending. Lower priority now that the watchdog catches it.

If Option 1 is later attempted, distinguish in the cron ticker's `next_run_at` write path between "ran on schedule" and "fast-forwarded without firing." A separate `fast_forward_count` counter per job, exposed in `jobs.json`, would let the watchdog read it directly instead of inferring it.