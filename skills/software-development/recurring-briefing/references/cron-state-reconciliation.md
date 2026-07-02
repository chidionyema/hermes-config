# Cron State Reconciliation

The recurring briefing's unique value-add: cross-referencing `hermes cron list` `last_status` fields against the disk artifacts those crons are supposed to produce. A `last_status: ok` does not mean the cron worked. This file is the table of common cases.

## Why This Matters

A cron can be in one of five states, and the briefing must report all five correctly:

| Disk state | Cron self-report | What it means |
|------------|------------------|---------------|
| File exists with content | `last_status: ok` | Working as expected |
| File exists but stale (>1 cycle late) | `last_status: ok` | **Lying** — cron is dispatching but not producing output |
| File does not exist | `last_status: ok` | **Lying** — silent failure |
| File does not exist | `last_status: error` | Honest failure |
| File exists, partial content | `last_status: error` | Crashed mid-write |

The briefing's job is to report the **disk state**, with the cron state as a corroborating (but not authoritative) signal. When they disagree, surface the disagreement as a P0 finding.

## Cross-Reference Table by Cron

### `daily-self-reflection`
**Cron schedule:** `0 18 * * *` (6pm daily)
**Should produce:** `~/.hermes/logs/reflection/$(date -v-1d +%Y-%m-%d).md`

**Reconciliation probes:**
```bash
# What the cron says
hermes cron list | grep -A4 "daily-self-reflection" | grep "Last run"
# What the disk says
ls -la ~/.hermes/logs/reflection/ | tail -5
```

**State matrix:**
- `Last run: ok` + reflection file exists for today/yesterday → ✅
- `Last run: ok` + no reflection file for yesterday → 🔴 cron lying (this is the 8-day gap case in Otto's estate, 2026-07-02)
- `Last run: error` + no reflection file → 🟡 honest failure, surface error
- `Last run: error` + reflection file exists → 🟢 cron recovered on retry

**Common failure mode:** `daily_reflection.py` had a hardcoded path to `~/Documents/code/.hermes/OBJECTIVES.md` instead of `~/.hermes/OBJECTIVES.md` (the actual file). The cron would `exit 1` with `Operation not permitted`. Fix: patch the path. Auto-fixed in the 2026-06-23 audit.

### `morning-briefing`
**Cron schedule:** `0 9 * * *` (9am daily)
**Should produce:** a delivered report (the briefing itself)

**Reconciliation probes:**
```bash
hermes cron list | grep -A4 "morning-briefing" | grep "Last run"
```

**State matrix:**
- `Last run: ok` → ✅
- `Last run: error: TimeoutError ... 936s` → 🔴 the cron is timing out. The fact that the briefing is being delivered through an alternate path doesn't fix the cron.
- `Last run: error: TimeoutError ... > 600s` (limit 600s) → 🔴 same. The 600s limit is the schedule budget.

**Common failure mode:** the briefing is generated as a multi-step synthesis (read 5+ files, format the report). When the cron is in agent mode (not no-agent mode), the model takes >600s to produce the response. The 9am delivery in Otto's estate has been erroring for 9+ days with this exact pattern (as of 2026-07-02).

**The briefing's job here:** surface the cron failure as a P0 finding in the "Cron health" section. The briefing is still delivered (via the alternate path), but the cron is broken. Future auto-deliveries will also fail.

### `daily-strategist-audit`
**Cron schedule:** `0 8 * * *` (8am daily)
**Should produce:** `~/.hermes/reports/strategist-audit-YYYY-MM-DD.md`

**Reconciliation probes:**
```bash
hermes cron list | grep -A4 "daily-strategist-audit" | grep "Last run"
ls -la ~/.hermes/reports/strategist-audit-*.md 2>/dev/null | tail -3
```

**State matrix:**
- `Last run: ok` + report exists for today → ✅
- `Last run: ok` + report missing for today → 🟡 cron dispatched but the audit crashed mid-write (the 7am interrupted case)
- `Last run: error: TimeoutError` → 🟠 audit was too complex to complete
- `Last run: error: ...` + report exists → 🟢 cron retried successfully

**Cross-reference with task state:** if `~/.hermes/task-state/current_task.json` shows `interrupted: true, tool_calls_completed: 0` from today's audit, the audit started but aborted before any work. Report as P0: "Strategist audit interrupted at startup — no report produced."

### `health-watchdog`
**Cron schedule:** every 15m
**Should produce:** silent when healthy, alert entries in `~/.hermes/logs/alerts/watchdog.jsonl` when unhealthy

**Reconciliation probes:**
```bash
hermes cron list | grep -A4 "health-watchdog" | grep "Last run"
tail -5 ~/.hermes/logs/alerts/watchdog.jsonl
```

**State matrix:**
- `Last run: ok` + watchdog.jsonl has new entries → ✅
- `Last run: ok` + watchdog.jsonl has no new entries in 30m → 🟡 watchdog is running but finding nothing (may be healthy, may be broken — investigate)
- `Last run: error` → 🔴 watchdog is broken. If the watchdog can't run, no other alerts are detected. **P0.**
- `Last run: error: ...UnboundLocalError...` → 🔴 script bug. Fix required.

**The "watchdog's own errors" pitfall:** if the watchdog has an `UnboundLocalError` (e.g. `cannot access local variable 'datetime' where it is not associated with a value`), it exits 1 → that itself becomes an alert → watchdog re-runs → re-errors → re-alerts. The result is hundreds of duplicate alerts per day. The briefing should:
- Report the underlying script bug
- Note "watchdog is erroring on its own execution; the alert count is inflated"
- NOT report 100+ alerts as 100 separate findings

### `idle-continuous-learning`
**Cron schedule:** every 30m
**Should produce:** `~/.hermes/logs/maintenance/idle-learning-runs.jsonl` (one entry per run)

**Reconciliation probes:**
```bash
hermes cron list | grep -A4 "idle-continuous-learning" | grep "Last run"
tail -5 ~/.hermes/logs/maintenance/idle-learning-runs.jsonl
```

**State matrix:**
- `Last run: ok` + idle-learning-runs.jsonl has new entry → ✅
- `Last run: ok` + run log entry is `reason: preempted` → 🟢 designed exit (script ran for 120s and was killed by the scheduler; the next cycle picks up)
- `Last run: ok` + run log entry is `reason: Complete, failed_phases: <X>` → 🟠 pipeline ran but one phase failed
- `Last run: error: ... Script timed out after 120s` → 🟢 this is the `reason: preempted` case; the cron self-reports "error" but it's designed

**Critical distinction:** `reason: preempted` is a normal exit, not a failure. The watchdog's `CRON_ERROR` classifier has historically misclassified this as a real error. The briefing should treat it as healthy.

### `repo-health-check`
**Cron schedule:** every 2h
**Should produce:** new entry in `~/.hermes/logs/health/repo-health.jsonl`

**Reconciliation probes:**
```bash
hermes cron list | grep -A4 "repo-health-check" | grep "Last run"
wc -l ~/.hermes/logs/health/repo-health.jsonl
date
```

**State matrix:**
- `Last run: ok` + JSONL has an entry from the last 2h → ✅
- `Last run: ok` + JSONL's most recent entry is >2.5h old → 🟡 cron is dispatching but the probe is failing
- `Last run: error` → 🟠 honest failure

### `uncommitted-watch`
**Cron schedule:** every 6h (`every 360m`)
**Should produce:** either no output (healthy) or a message naming uncommitted files (unhealthy)

**Reconciliation probes:**
```bash
hermes cron list | grep -A4 "uncommitted-watch" | grep "Last run"
# The script writes to ~/.hermes/logs/uncommitted-watch.log (or similar) on findings
```

**State matrix:**
- `Last run: ok` + no log entry → ✅ silent because healthy
- `Last run: ok` + log entry with file count → 🟡 surface the count

### `hermes-config-auto-push`
**Cron schedule:** hourly (`0 * * * *`)
**Should produce:** git commits to `~/.hermes` config repo when files change

**Reconciliation probes:**
```bash
hermes cron list | grep -A4 "hermes-config-auto-push" | grep "Last run"
cd ~/.hermes && git log --oneline -5
```

**State matrix:**
- `Last run: ok` + recent commits → ✅
- `Last run: ok` + 295 uncommitted files (the 2026-06-22 audit case) → 🔴 the `|| echo "Push failed"` pattern in `auto-push.sh` is swallowing the real git error. The cron self-reports success but pushes have been failing for 19h.

**Common failure mode:** `auto-push.sh` uses `git push 2>&1 || echo "Push failed"`. The `||` swallows the actual error message and replaces it with a generic "Push failed" line. The cron output claims "Pushed N files" every hour even when push has been failing for 19h. The briefing should cross-reference `git log` to detect this case.

## General Reconciliation Logic

For ANY cron, the briefing should follow this sequence:

```bash
# 1. What the cron says
hermes cron list | grep -A6 "Name: <cron_name>" | grep "Last run"

# 2. What the disk says (varies by cron)
ls -la <expected_artifact_path> | tail -3

# 3. Compare
```

If `Last run: ok` and disk artifact is present and fresh → ✅
If `Last run: ok` and disk artifact is missing or stale → 🔴 cron is lying
If `Last run: error` and disk artifact is present → 🟢 cron recovered
If `Last run: error` and disk artifact is missing → 🔴 honest failure, surface error

## When to Bother Reconciling

Not every cron warrants a reconciliation probe in every briefing. The brief should reconcile when:
- The cron is on a daily-or-slower cadence (its absence is newsworthy)
- The cron produces a user-visible artifact (briefing, report, notification)
- The cron is in the user's "must work" list (autopush, watchdog, daily reflection)

Hourly-and-faster crons (idle-learning, improvement-probe, watchdog itself) only need reconciliation if the cron has been erroring for >24h. A single errored run is not a briefing finding; a sustained pattern is.

## Pitfalls

**1. The cron self-report can be cached.** `hermes cron list` reads from `~/.hermes/cron/jobs.json`. The cron updates this on each run, but a stuck daemon may show stale state. If the cron shows `Last run: ok` but the daemon process is not in `ps`, the cron self-report is stale.

**2. `hermes cron list` may not show all crons.** Profile-specific crons live under `~/.hermes-profiles/<name>/cron/jobs.json`. Use `hermes cron list --profile <name>` to see them. The default profile is what `hermes cron list` shows.

**3. The `Script:` field can be wrong.** If a cron was edited with `hermes cron edit <id> --script "#!/bin/bash\n..."`, the script field is a literal string. The cron dispatcher treats it as a path, fails with "Script not found", and the job silently no-ops every run. Detection: `hermes cron list | grep -E "Script:.*#\!"`.

**4. The `Deliver: origin` flag is what pages the user.** A cron with `Deliver: origin` (vs `Deliver: local`) sends the report to the user's notification channel. The briefing should note which crons have `origin` delivery, as they're the ones the user sees directly. Get the count: `hermes cron list | grep -c "Deliver:.*origin"`.

**5. The cron may be in a different profile.** If the user has multiple Hermes profiles, the cron that delivers THIS briefing may be in `default`, but the user's "real" crons are in `~/.hermes-profiles/work/`. The briefing should reconcile the profile that delivered it (the active profile), not the user's primary profile.
