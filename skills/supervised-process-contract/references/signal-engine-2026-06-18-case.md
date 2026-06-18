# Signal Engine Daemon — 2026-06-18 Case Study

The session that produced the wrong-entry-point discovery. Use this as a worked example when triaging any "supervised daemon keeps dying" report.

## The Setup

- **Project:** Signal Engine at `~/Documents/code/signalengine`
- **Watchdog:** cron job `76074b28a126`, script at `~/.hermes/scripts/signal-engine-daemon-watchdog.sh`
- **Schedule:** every 5 minutes (`*/5 * * * *`)
- **Watchdog pattern (BAD):**
  ```bash
  if pgrep -f "signal-engine" > /dev/null 2>&1; then
    exit 0
  fi
  echo "⚠️  Signal Engine daemon not running. Restarting..."
  cd ~/Documents/code/signalengine
  nohup uv run signal-engine-run > daemon.log 2>&1 &
  echo "  Started PID $!"
  exit 0
  ```
- **Symptom:** watchdog fires every 5 min, every time, all day. PIDs incrementing. Daemon "dies" within minutes of each restart.

## The Investigation Path (in order)

### 1. Historic watchdog output
```bash
ls -1t ~/.hermes/cron/output/<job_id>/*.md | head -10 | xargs cat
```
**Finding:** "Signal Engine daemon not running. Restarting... Started PID 57062" repeated at 18:50, 18:55, 19:00, 19:05 — exactly the 5-min cadence. Sometimes silent (19:10, 19:15) when a startup finally lived.

### 2. Daemon log (stdout-merged, block-buffered)
```bash
tail -20 ~/Documents/code/signalengine/daemon.log
```
**Finding:** Last lines were "Ingesting data" then "Extracting features" then [silence]. No traceback. The traceback was in stderr (never captured) OR block-buffered stdout (never flushed).

### 3. OOM/jetsam hypothesis (negative)
```bash
log show --last 1h --predicate 'eventMessage CONTAINS[c] "jetsam" OR eventMessage CONTAINS[c] "low memory"' | tail -40
```
**Finding:** No python processes killed. Only `RunningBoard` chatter about system services. OOM ruled out.

### 4. Memory pressure (negative)
```bash
memory_pressure | head -10
sysctl vm.swapusage
```
**Finding:** 16GB RAM, 1GB swap used, no throttling. Plenty of headroom.

### 5. The decisive question Claude Code asked
**"What are the 'Ingesting data' / 'Extracting features' log lines actually in? Are they in daemon.py?"**

```bash
grep -rn --include='*.py' -e "Ingesting data" -e "Extracting features" signal_engine/
```
**Finding:** Those strings are in `signal_engine/scheduler/run_m1.py:53,84` — NOT in `daemon.py`. The watchdog was launching the wrong program.

### 6. The entry-point reality check
```bash
grep -A2 "\[project.scripts\]" ~/Documents/code/signalengine/pyproject.toml
```
**Output:**
```
[project.scripts]
signal-engine = "signal_engine.cli:cli"
signal-engine-run = "signal_engine.scheduler.run_m1:run_e2e"   # ← what the WATCHDOG launches
```

The watchdog launches `signal-engine-run` → `run_m1:run_e2e()`, which is a **one-shot batch job** (Ingest → Features → Validation → Paper → Recon → Signal → return). It runs the pipeline once, returns a signal, exits 0.

The **actual long-lived daemon** is `python -m signal_engine.daemon:main`, which has the `while True: run_cycle(runner); sleep(tick_interval)` loop. The watchdog never supervised this one.

### 7. Confirmation via direct repro
```bash
cd ~/Documents/code/signalengine
PYTHONUNBUFFERED=1 ./.venv/bin/python -m signal_engine.daemon >/tmp/se.out 2>/tmp/se.err &
```
**Result:** Daemon stable for 10+ minutes (the original "5-min death" pattern never recurs). The real daemon is healthy; the watchdog was supervising a one-shot job.

## The Two-Line Fix

Replace the watchdog's launch line with:
```bash
# OLD (wrong)
nohup uv run signal-engine-run > daemon.log 2>&1 &

# NEW (correct)
PYTHONUNBUFFERED=1 nohup ./.venv/bin/python -m signal_engine.daemon > daemon.out.log 2> daemon.err.log &
```

This also:
- Strips the VIRTUAL_ENV (uv's auto-fix warning goes away)
- Splits stderr (next time it does die, we capture the traceback)
- Removes block-buffering silent-death

## Lessons Embedded in the Skill

1. **Verify the entry point is actually a loop before debugging daemon crashes.** A one-shot job supervised as a daemon is a guaranteed restart loop.
2. **Always grep for the log markers in the source** — "what file produces this line?" is a one-minute question that takes five if you don't think to ask it.
3. **Block-buffered stdout + merged stderr = silent death even when the cause is benign.** The PYTHONUNBUFFERED+split pattern is the universal fix.
4. **VIRTUAL_ENV warnings from uv are auto-fixes**, not defects. Don't chase them first.
5. **OOM is the silent killer #1 hypothesis on macOS** but is ruled out by `log show` in 5 seconds. Always check.

## Cost of the Mistake

- Days of "signal-engine-daemon-watchdog" alerts polluting Telegram
- A foregrounded reproduction that hung the conversation (until I switched to background mode)
- Two memory-budget churns to save the new operating rules
- A real signal-engine daemon was OFFLINE the entire time the watchdog was "supervising" the wrong program

The biggest waste was **debugging the wrong program** — every minute spent on `run_e2e` exit causes was a minute not spent on the real question (which entry point should the watchdog supervise?).
