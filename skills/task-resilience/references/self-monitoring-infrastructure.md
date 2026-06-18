# Self-Monitoring Infrastructure

Built during session 2026-06-18. The complete monitoring and self-healing stack for Otto.

## Architecture

```
watchdog.py (15min cron) → check functions → self-healer.py (auto-fix) → alert log
     ↓                          ↓
  dedup (compare to last)   audit-trail.py (permanent record)
     ↓
  stdout → cron → Telegram (only NEW alerts, never noise)
```

## Components

### 1. Health Watchdog (`scripts/watchdog.py`)
- Runs every 15 minutes via cron (no-agent mode)
- Checks: cron job staleness (>26h without run), git dirty state (>50 files), gateway process, disk usage (>90%), idle-learning errors, policy firings
- Dedup: compares current alerts against last run — only outputs NEW alerts to stdout (which cron delivers to Telegram)
- Auto-heal: calls `self-healer.py` on every run regardless of new/known status

### 2. Self-Healer (`scripts/self-healer.py`)
Auto-fixes what it can:
- `CRON_STALE`/`CRON_ERROR` → clears the error state in `cron/jobs.json` so the watchdog stops alerting
- `GATEWAY_DOWN` → restarts gateway process via `hermes gateway run --replace`
- `POLICY_NEVER_FIRED` → archives the policy (moves to `policies/archived/`)
- `IDLE_ERROR` → clears idle-learning error state
- All fixes logged to `logs/audit/decision-trail.jsonl` with `decision_type: auto_heal`

### 3. Audit Trail (`scripts/audit-trail.py`)
Permanent append-only log at `logs/audit/decision-trail.jsonl`.
Every entry: timestamp, decision_type, description, rationale, outcome, state_snapshot (policy count at time of decision).
Wired into `task_state.py mark_task_complete()` — fires on every task completion.

### 4. Repo Health Check (`scripts/repo-health-check.py`)
- Runs every 2 hours via cron (no-agent)
- Tests: signalengine (pytest), lux (jest), prospector (pytest)
- Only reports on STATE CHANGE (pass→fail or new dirty files) — silent on no-change
- Maintains history at `logs/health/repo-health.jsonl`

### 5. Cross-Project Bridge (`scripts/cross-project-bridge.py`)
- Runs in idle-learning pipeline (after gap-finding)
- Reads latest repo-health results
- If any repo is failing or dirty, creates structured entries in the self-regression corpus
- Bridges: test failures → policy learning signal

### 6. Trend Analyzer (`scripts/trend-analyzer.py`)
- Runs in idle-learning pipeline
- Compares across days: reflections × near-miss × outcomes × corpus growth
- Produces structured JSON at `logs/trends/trend-*.json`
- Surfaces recurring patterns (same policy untriggered in multiple scans, declining velocity)

## Alert Dedup Logic

```
current_alerts = [A, B, C]
prev_alerts = [A, B]        # from last watchdog run
new_alerts = [C]             # only C is new → push to Telegram
print(f"NEW — 1 issue(s): C")
known = [A, B]               # silent on these
```

## Error States That Auto-Clear

When watchdog detects an error and self-healer fixes it, the NEXT watchdog run will:
1. Not find the error (it was cleared)
2. Not output anything (no change since last run)
3. The cron job's `deliver: origin` sends nothing → Telegram stays quiet

## The Self-Improvement Loop (as of 2026-06-18)

```
test fails → health check detects → cross-project bridge logs to corpus →
  idle-learning finds gap → gap-finding reports → reflection auto-fills →
    morning briefing surfaces → user prioritizes → agent fixes → outcome logged →
      outer loop evaluates → meta-improver tunes pipeline
```

No manual steps between test failure and pipeline tuning.
