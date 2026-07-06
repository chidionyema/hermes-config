# Silent-Stretch Detection — Cron Silent Failure Pattern

**Discovered:** 2026-07-06 daily-strategist-audit
**Status:** P0 active finding; structural fix pending
**Owner:** cron ticker (not watchdog)

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

## The Right Fix (Pending)

**File:** cron ticker source (location TBD — likely `hermes-cron` package or `~/.hermes/scripts/cron-ticker.py`).
**Change:** When the ticker fast-forwards a missed job, do NOT update `next_run_at` until the job actually fires. Track missed-but-not-fired runs as a separate counter. On N consecutive fast-forwards for the same job, write a `cron.jobs: silent-stretch detected` warning to the agent log so the watchdog's existing classifier can pick it up.

**Alternative simpler fix (if cron ticker source is hard to change):** Add a watchdog check that compares `last_run_at` against the schedule's expected interval — `0 8 * * *` should run at most 26h apart. The existing CRON_STALE check uses `next_run_at`; the new check should use `last_run_at` AND the schedule expression to compute "expected last_run_by." This is a parallel check, not a replacement.

**Diagnostic command for next audit:**
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

- 9-day audit gap (06-24 → 07-01): gateway was down. Watchdog silent. Same "every layer reports green" symptom.
- 7-day daily-cron silence (this audit): cron ticker behind schedule. Watchdog silent. Same symptom.

The root cause class is "monitoring layer trusts data written by the failing layer." A structural enforcer for this class: every watchdog check that reads a state field must also include a sanity check against the **raw event log** for the same entity, with at-least-one-check-per-day cadence. If the raw log is empty but the state field is "fresh," the silence is a silent stretch.

## Carry-Over

This finding has been re-prescribed in audits 07-02, 07-03, 07-06. As of 07-06, the layer-confusion trap was identified — the fix lives in the cron ticker, not the watchdog. Auto-execute was BLOCKED. Next audit should either:
1. Patch the cron ticker source to distinguish "fast-forwarded" from "ran on schedule," or
2. Add the parallel `last_run_at` check to the watchdog (simpler, partial fix).
