# Project Probe Locations

Where to find diagnostics for each tracked project when the repo directory itself is inaccessible (macOS sandbox, permission issues) or when you need a fast read-only state check.

## Prospector (`/Users/chidionyema/Documents/code/prospector`)

### Primary diagnostics (always accessible)

| Artifact | Path | Content |
|----------|------|---------|
| **Daemon gen log** | `/tmp/prospector_gen.log` | Last batch output: generated candidates, vetting results, PASS/KILL counts, alerts (zero_yield, dead_gate, quality_decay), token totals. Written by the daemon each tick. |
| **Pipeline summary** | `/tmp/prospector_summary.md` | Comprehensive pipeline documentation: all 8 stages with file:line references, operator routing, output locations. Stable reference. |
| **Graphify analysis** | `~/.hermes/reports/project-status-prospector.md` | Structural analysis from last graphify run: node/edge counts, god objects, low-cohesion communities, cross-namespace surprises. Generated at commit `aaa23c0`. |
| **Graphify log** | `~/.hermes/logs/graphify-prospector.log` | Last graphify run: AST extraction progress, semantic extraction chunks, token costs. |

### Daemon state (no repo access needed)

```bash
# Is the daemon running?
launchctl list | grep prospector

# Full daemon config (paths, args, env, stdout/stderr targets)
launchctl print gui/$(id -u)/com.prospector.scheduler
```

Daemon details:
- **Label:** `com.prospector.scheduler`
- **Command:** `python -m prospector.scheduler.run_scheduled --daemon --interval 7200 --config <repo>/config.yaml`
- **Plist:** `~/Library/LaunchAgents/com.prospector.scheduler.plist`
- **stdout:** `<repo>/store/scheduler/launchd.out.log`
- **stderr:** `<repo>/store/scheduler/launchd.err.log`

### Cron guard (hourly, dry-run only)

- **Job ID:** `df1c49144256`
- **Script:** `~/.hermes/scripts/prospector-run.sh`
- **Cadence:** Hourly (`0 * * * *`)
- **What it does:** `uv run --directory <repo> python -m prospector.scheduler.run_scheduled --once --dry-run` — guard probe only. Evaluates spend ceiling + PAUSE switch, writes one tick, exits. Sub-second. Does NOT generate.
- **Real generation:** Owned entirely by the launchd daemon above.

### Repo-internal diagnostics (require repo access)

| Artifact | Path (relative to repo) |
|----------|------------------------|
| Scheduler ticks | `store/scheduler/ticks.jsonl` |
| Scheduler heartbeat | `store/scheduler/heartbeat.json` |
| Batch diagnostics | `store/scheduler/DIAGNOSTICS_LATEST.txt` |
| Dossier DB | `store/prospector.db` (SQLite, WAL mode) |
| Dossier JSONs | `store/dossiers/<candidate_id>.<decision>.json` |
| Pending signals | `signals/pending/<hash>.json` |

## Signal Engine (`/Users/chidionyema/Documents/code/signalengine`)

*(To be populated)*

## LUX (`/Users/chidionyema/Documents/code/lux`)

*(To be populated)*
