# Monitoring & Audit Architecture

## Health Watchdog

`watchdog.py` runs every 15min via cron `abf69d5df846` (no-agent). Checks:

- **Cron health:** every job's `last_run_at`, `last_status`, `last_error`. Stale = not run in 26h+.
- **Git health:** uncommitted file count from `git status --porcelain` in `~/.hermes`.
- **Gateway health:** process check (`ps aux | grep hermes_cli.main gateway`) + log file mtime.
- **Disk usage:** `df -h /` > 90%.
- **Policy firings:** any policy with 0 hits after 1+ day since creation.
- **Idle-learning errors:** consecutive failures in the improvement pipeline.

All alerts written to `~/.hermes/logs/alerts/watchdog.jsonl`. Each entry: `timestamp`, `alert_count`, `alerts[]`, `healthy`.

**Known alert patterns:**

| Alert type | Meaning | Fix |
|---|---|---|
| `CRON_ERROR: <name> errored: Broken pipe` | No-agent script produced output it shouldn't have | Strip stdout for below-threshold cases |
| `CRON_ERROR: <name> errored: Script exited with code 1` | A sub-phase returned non-zero | Wrap with `|| true` or use `set -eo pipefail` |
| `GATEWAY_IDLE: log not updated in N minutes` | Gateway process running but not processing messages | Normal if the user hasn't messaged — 30min threshold is generous |
| `POLICY_NEVER_FIRED: pol-* has 0 hits after N days` | Policy was created but retrieval layer never selects it | Check scope domain matches corpus domain taxonomy |
| `GIT_DIRTY: N uncommitted files` | Accumulated work not pushed | Check `hermes-config-auto-push` cron (every hour) has been running |

**Strategist audit integration:** The daily audit at 8am reads `watchdog.jsonl` and surfaces active alerts. Alerts more than 24h old are shown at reduced priority — repeat alerts across days indicate a structural issue.

## Audit Trail

`audit-trail.py` records every structured decision to `~/.hermes/logs/audit/decision-trail.jsonl`. Append-only JSONL.

**When entries are created:**
1. **Every task completion** — via `mark_task_complete()` in `task_state.py`, which calls `audit-trail.py task_complete "<desc>" "auto-logged"` as a subprocess.
2. **Manual logging** — after structural changes (new cron job, policy addition, config change), call `uv run python3 ~/.hermes/scripts/audit-trail.py <type> <desc> <rationale>`.

**Entry schema:**
```json
{
  "timestamp": "2026-06-18T13:10:09Z",
  "decision_type": "task_complete",
  "description": "Built monitoring layer: watchdog + audit trail + fixes",
  "rationale": "4 active alerts found, fixed broken pipe...",
  "outcome": "pending",
  "state_snapshot": { "policy_count": 11, "active_count": 11 },
  "source": "auto"
}
```

**Replay:** `uv run python3 ~/.hermes/scripts/audit-trail.py --replay [N]` shows last N entries.

## Strategist Audit (8am daily)

Cron `85385abb646d` runs a Claude agent that reads all state files including watchdog alerts and trend analysis. See "Daily strategist audit" in the main SKILL.md.

**Sources read:**
- `logs/reflection/YYYY-MM-DD.md` — yesterday's self-reflection
- `logs/self-regression-corpus.json` — failure corpus
- `logs/regression-report.md` — coverage %
- `logs/maintenance/` — latest gap-finding and near-miss reports
- `logs/alerts/watchdog.jsonl` — active alerts
- `logs/trends/trend-*.json` — cross-session trends
- `policies/` — all policies
- `cron/jobs.json` — cron job status
- `meta/change-outcomes.jsonl` — outcome velocity

## Alert Escalation Hierarchy

Currently: watchdog → alert log → strategist audit (8am) → user sees in daily briefing.

Gap: No mid-day push for critical alerts. If gateway truly goes down, the user won't know until 8am next day. Candidate improvement: wire high-severity alert detection into a Telegram push via a cron job that runs every hour and only delivers if there are new high-severity alerts.
