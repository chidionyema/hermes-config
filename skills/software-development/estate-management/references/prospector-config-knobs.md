# Prospector Daemon Configuration Knobs

Where each generation parameter lives and how to change it safely.

## batch_size — candidates per tick

**File:** `~/Documents/code/prospector/config.yaml`
**Key:** `schedule.batch_size`
**Example:**
```yaml
schedule: { cadence: daily, batch_size: 15 }
```

The daemon (`com.prospector.scheduler`) reads this on every tick via `_batch_size(cfg, candidates)`.
No restart needed for the daemon — it re-evaluates the guard/config every cycle.

**Pitfall:** Changing batch_size without checking the tick deadline. The hard deadline in
`run_scheduled.py` must comfortably exceed `batch_size × per-candidate-wall-time`.

## Tick hard deadline

**File:** `~/Documents/code/prospector/prospector/scheduler/run_scheduled.py`
**Constant:** `_TICK_HARD_DEADLINE_S`
**Default:** `10800` (3h) — env-overridable via `PROSPECTOR_TICK_DEADLINE_S`

```python
_TICK_HARD_DEADLINE_S = int(os.environ.get("PROSPECTOR_TICK_DEADLINE_S", "10800"))  # 3h
```

If a tick exceeds this deadline, the daemon force-exits and launchd KeepAlive relaunches it.
The deadline must be comfortably above normal batch runtime (conservative: ~10 min/candidate).

**History:**
- Was 4500 (75 min) for batch_size=5
- Bumped to 10800 (3h) when batch_size went to 15 (founder directive 2026-07-31)

## Daemon interval — time between ticks

**File:** `~/Library/LaunchAgents/com.prospector.scheduler.plist`
**Flag:** `--interval` in `ProgramArguments`
**Values:** 3600 (1h), 7200 (2h), 14400 (4h)

Change via the phone panel (params) or manually edit the plist + restart.

## Concurrency

**File:** `~/Library/LaunchAgents/com.prospector.scheduler.plist`
**Env var:** `PROSPECTOR_CURSOR_CONCURRENCY` in `EnvironmentVariables`
**Values:** 2, 4, 8

Controls how many parallel cursor_cli grounding calls the daemon makes.

## Daily spend cap

**File:** `~/Documents/code/prospector/config.yaml`
**Key:** `spend.daily_cap_usd`

```yaml
spend:
  daily_cap_usd: 20.0
  warn_at_usd: 15.0
```

## PAUSE kill switch

**File:** `~/Documents/code/prospector/store/scheduler/PAUSE`

If this file exists, the daemon idles (re-evaluates every cycle). Remove to resume.
Can be toggled via phone panel: `estate:pd_pause` / `estate:pd_unpause`.

## Restart protocol after code/config changes

The daemon re-evaluates config.yaml every tick — no restart needed for config changes.
But if you changed `run_scheduled.py` (the tick deadline constant or any Python code),
you MUST restart:

```bash
launchctl kickstart -k gui/$(id -u)/com.prospector.scheduler
```

This sends SIGKILL to the current process; launchd KeepAlive relaunches immediately.

## Progress output timestamps

**File:** `~/Documents/code/prospector/prospector/progress.py`
**Function:** `_emit()`

Every progress line (alerts, batch diagnostics, steps, banners) written to stderr
now carries a UTC timestamp prefix: `2026-07-31 14:20 UTC  🚨 [zero_yield] ...`

This is what populates the `launchd.err.log` that the phone panel's "Recent log" tails.
Added 2026-07-31 — before this, the entire daemon log output was dateless.

## Verification after changes

```bash
# Check the daemon picked up the new batch_size
python3 -m prospector.scheduler.run_scheduled --once --dry-run 2>&1 | head -5

# Check the current config value
grep -A1 'schedule:' ~/Documents/code/prospector/config.yaml
```
