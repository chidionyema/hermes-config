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

### Phone control / status display code

The Prospector daemon status card shown in Telegram (the `⚙️ Prospector daemons` panel) is rendered by:

```
~/.hermes/hermes-agent/gateway/operator_shell/prospector_daemon.py
```

Key functions:
| Function | Line ~ | What it does |
|----------|--------|-------------|
| `render_prospector_daemon()` | 640 | Full status card: daemon states, heartbeat, cron outcomes, recent log tail |
| `render_logs()` | 717 | Per-daemon log viewer (scheduler/watchdog/control-center) |
| `render_params()` | 449 | Safe parameter knobs (interval, concurrency, batch size, daily cap) |
| `glance_line()` | 908 | One-liner for fleet overview |
| `_heartbeat()` | 177 | Reads `store/scheduler/heartbeat.json`, computes staleness, returns phase+age |
| `_tail_lines()` | 212 | Reads last N non-blank lines from daemon log files, strips ANSI |
| `_log_mtime_ago()` | 198 | Returns relative age of newest log file in a tuple of paths |

The display assembles data from three independent sources:
1. **launchctl** — daemon running/pid/state (via `launchctl_state()`)
2. **heartbeat.json** — scheduler phase, cycle count, last-write timestamp (via `_heartbeat()`)
3. **launchd log files** — stderr/stdout from the scheduler process (via `_tail_lines()`)

**Pitfall — timestamps:** The prospector scheduler (`prospector.scheduler.run_scheduled`) does not timestamp its own log lines. The render function originally only showed relative ages (`57m`, `2h ago`). After 2026-07-31, the display includes: capture time at top (`_captured 2026-07-31 08:48 UTC`), heartbeat absolute `ts` alongside relative age, and log file mtime in the "Recent log" header. Individual log lines (zero_yield, dead_gate alerts) still lack per-line timestamps until the scheduler itself is updated. Fix is in the repo at `prospector/scheduler/run_scheduled.py`.

**Pitfall — TCC sandbox:** `~/Documents/code/prospector/` and its subdirectories are macOS TCC-protected. `terminal()`, `read_file()`, and `search_files()` all fail with `Operation not permitted` on files under that tree. Access the repo via a separately-granted tool (Claude Code, Cursor, direct terminal) or via the no-repo probes listed above.

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

### Daemon watchdog

- **Cron job:** `signal-engine-daemon-watchdog` (job ID `76074b28a126`)
- **Cadence:** Every 5 min (`*/5 * * * *`)
- **Script:** `~/.hermes/scripts/signal-engine-daemon-watchdog.sh`
- **Working dir:** `/Users/chidionyema/Documents/code/signalengine`
- **Behaviour:** Checks if `signal_engine.daemon` is running. If alive, produces no output (silent). If dead, restarts it and logs a `CRON_ERROR` alert with the new PID.

### Diagnosing daemon instability

When the watchdog shows repeated restart events (e.g., 220 events accumulated), the daemon is crashing shortly after each restart. Diagnostic flow:

1. **Check watchdog alert count:** `grep -c "signal_engine.daemon was not running" ~/.hermes/logs/alerts/watchdog.jsonl`
2. **Check last restart PID:** last matching entry in watchdog.jsonl gives the most recent PID
3. **Check daemon logs:** The watchdog script invokes the daemon; check `<repo>/logs/` for crash traces
4. **Check process tree:** `ps aux | grep signal_engine` — is the daemon currently alive? How long has it been running? (use `ps -o etime -p <pid>`)
5. **Check for resource contention:** Is the daemon colliding with another process on the same port, lock file, or database?

### Signal engine diagnostics (require repo access)

| Artifact | Path (relative to repo) |
|----------|------------------------|
| Daemon logs | `logs/signal_engine.log` |
| Test suite | `pytest -n 2 -m "not slow"` (~90s, 309 tests baseline) |
| Config | `config.yaml` |

## LUX (`/Users/chidionyema/Documents/code/lux`)

*(To be populated)*
