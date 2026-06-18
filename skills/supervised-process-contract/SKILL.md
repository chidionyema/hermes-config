---
name: supervised-process-contract
description: How to supervise long-running daemons in Otto (launchd + thin wrapper, exit-cause captured by parent, circuit breaker, stderr split, OOM hypothesis first)
version: 1.1.0
---

# Supervised Process Contract — Otto Pattern

A reusable contract for **any** long-lived daemon Otto supervises. Distilled from a 2026-06-18 Claude Code review of the signal-engine watchdog incident.

**Worked example:** see `references/signal-engine-2026-06-18-case.md` for the full investigation path that produced this contract — including the wrong-entry-point discovery, the unbuffered-stderr-split repro pattern, and the OOM hypothesis check.

## ⚠️ Wire-up Status (2026-06-18, audit finding)

A meta-audit on 2026-06-18 found that this skill is a **specification without enforcement**: the canonical example (signal-engine-daemon-watchdog.sh) still uses the anti-patterns this skill is meant to prevent (`pgrep -f signal-engine` substring match + wrong entry point). Documenting a contract and not enforcing it is the same as not having one — the next incident will hit the exact same failure.

**Maintenance rule (new):** every time this skill is loaded, the agent must check the table below. If any row is `❌ orphan`, the agent surfaces to the user and offers to wire it up. Adding a row requires verifying the watchdog actually follows every section of this contract, not just that the skill file exists.

| Daemon | Watchdog path | Status | Last verified |
|---|---|---|---|
| signal-engine | `~/.hermes/scripts/signal-engine-daemon-watchdog.sh` | ❌ orphan — still uses `pgrep -f signal-engine` + launches one-shot `run_e2e` | 2026-06-18 |
| (others TBD) | | | |

When all rows are ✅, this skill is actually enforced.

## Core Principles (in order of importance)

1. **The supervisor is the source of truth for why something died.** A dying process cannot file its own report (`atexit` / signal handlers do NOT run on `SIGKILL`, native segfault, `os._exit`). Capture exit cause from the *parent* via `wait()` / `$?`. Self-reporting is a nice-to-have for graceful exits only.
2. **"Silent death" is almost always a buffering/stderr artifact, not a real absence of a traceback.** Python block-buffers stdout when not a TTY. The traceback may exist but never flush. Always run with `PYTHONUNBUFFERED=1` and split stderr to a separate file.
3. **Check the OOM hypothesis first.** On macOS, OOM = jetsam `SIGKILL` = silent death with no traceback. `log show --last 30m --predicate 'eventMessage CONTAINS[c] "jetsam" OR ... "low memory"'` tells you in one command.
4. **Hygiene warnings are usually not the cause.** `VIRTUAL_ENV` mismatch warnings from uv mean uv is *fixing* the problem for you ("will be ignored"). Don't chase them first.
5. **Crash-only design + bounded backoff + circuit breaker for trading/research daemons.** Flapping a crashing process is worse than a clean halt. Restart with backoff, halt after N crashes in a window, page, wait for human.

## The Contract (5 elements)

### 1. launchd plist (per service)
- `KeepAlive{ SuccessfulExit=false, Crashed=true }` — only restart on crash, not clean exit
- `ThrottleInterval=10` — minimum 10s between restarts (backoff floor)
- `StandardErrorPath` / `StandardOutPath` → `~/.hermes/logs/<name>.{out,err}` (split streams, no merge)
- `EnvironmentVariables{ PYTHONUNBUFFERED=1 }` — disable Python block buffering
- Invoke `.venv/bin/python` directly, do NOT inherit `VIRTUAL_ENV`
- `RunAtLoad=true` if the service should start on boot

### 2. Thin supervisor wrapper (~50 lines)
- Run the child; on exit, write `~/.hermes/state/<name>.json` from **parent** perspective:
  - `exit_code`, `exit_signal` (decoded from `$?`), `exit_time`, `consecutive_restarts`, `breaker_state`, `last_log_tail` (last 50 lines of `.err`)
- Optionally: child writes a `graceful=true` marker for clean exits (parent is still source of truth)
- NO business logic — just lifecycle observation

### 3. Circuit breaker + paging
- N=3 crashes within 15 min → OPEN, stop restarting, emit ONE rich alert
- Breaker closes after process stays up ≥10 min continuously (proves no boot-loop)
- Distinguish "crashed" (restart with backoff) from "clean exit code 0" (do NOT restart)
- Backoff: `min(60s, 2^n)` → 1, 2, 4, 8, 16, 32, 60

### 4. Heartbeat (catches hangs, which crash-restart never sees)
- Every supervised service writes a liveness ping to `~/.hermes/state/<name>.heartbeat`
- A separate cron checks staleness (>5 min stale = alert)
- This is the ONLY way to detect deadlocks / infinite loops / stuck network calls

### 5. Recovery correctness (trading-specific)
- Assume restart is NOT safe until proven: idempotent recovery, no double-execution, no stale-state trading
- Test the recovery path explicitly — don't just hope

## First Diagnostic When a Daemon Goes Silent

```bash
# 1. Confirm it's actually dead
pgrep -fl <name>

# 2. Reproduce with stderr split + unbuffered
cd /path/to/service
PYTHONUNBUFFERED=1 .venv/bin/python -m <entrypoint> >daemon.out.log 2>daemon.err.log
echo "EXIT=$? SIGNAL=$((128 - $?))"

# 3. Check for OOM/jetsam (silent killer #1 on macOS)
log show --last 30m --predicate 'eventMessage CONTAINS[c] "jetsam" OR eventMessage CONTAINS[c] "low memory"' | tail -40

# 4. Read the stderr you should have been capturing all along
tail -50 daemon.err.log
```

`exit_code` + `exit_signal` + `daemon.err.log` + `log show` tell you in one run whether it's:
- Unhandled Python exception (full traceback in .err)
- OOM kill (signal 9 + jetsam log)
- Native segfault (signal 11, likely numpy/polars/duckdb/talib)
- Hanging process (heartbeat stale, nothing in .err)

## Why NOT These Alternatives

| Approach | Why rejected for Otto |
|---|---|
| docker | Adds clock/tz/networking complexity; fighting tz/UTC bugs is exactly the current pain point |
| supervisord | Second daemon to babysit on a single-user Mac |
| honcho | Procfile runner with no real supervision |
| Self-reporting via atexit | Doesn't fire on SIGKILL/segfault — false confidence |

## Anti-Patterns This Replaces

- ❌ `pgrep -f name; if dead: nohup cmd &` — the pattern that's failing right now
- ❌ Alert spam: "PID 1234 started" every 5 min, forever
- ❌ Treating `daemon.log` (stdout-merged) as if it had stderr
- ❌ Skipping OOM hypothesis because there's "no error"
- ❌ Letting a child process report its own death cause
- ❌ **Watchdog supervising the wrong entry point** — the most dangerous pattern, and the one that bit signal-engine 2026-06-18. The watchdog was launching `signal-engine-run` (a one-shot `run_e2e` batch job from `pyproject.toml`) and treating its normal exit as a "death" → restart loop forever. The real long-lived daemon was `python -m signal_engine.daemon:main` and was perfectly healthy. The watchdog was supervising the wrong program. **Always verify the watchdog's target is actually a long-lived loop, not a one-shot batch job.** A simple test: does the entry point have a `while True:` / event loop / `serve_forever()`? If not, it's not a daemon. If unsure, run the entry point manually and see if it exits on its own — if it does, the watchdog will restart-loop forever.
- ❌ **Chasing hygiene warnings before identifying the real defect** — the `VIRTUAL_ENV` mismatch warning was a uv-auto-fix, not the cause. Chasing it first is the "smarter bandage" trap. Identify the dominant defect first, then optionally fix the noise.

## How the Wrong-Entry-Point Defect Manifests

Symptom signature (matched 2026-06-18):
- Watchdog restarts the process every cron interval
- Each new "lifetime" is suspiciously short (matches one-shot job runtime, not daemon)
- The supervised process produces a few log lines, then exits cleanly
- The real long-lived daemon (or the correct entry point) is healthy and running fine independently
- OOM/jetsam hypothesis is negative
- Block-buffering hypothesis doesn't explain the "exit 0" behavior

**The grep that finds it:**
```bash
# Find the entry point the watchdog actually launches
grep -n "no_agent\|script" ~/.hermes/cron/jobs.json | grep <service>

# Check what the entry point actually does
cat ~/.local/bin/<entry>     # or:  grep -A2 "scripts" <project>/pyproject.toml
# Look for: while True, event loop, serve_forever, sleep(loop_interval)
# NOT: a single pipeline run that returns
```
