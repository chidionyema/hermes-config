# pytest-orphan-cleanup pattern

When a cron prompt tells the LLM agent to "run pytest" without a timeout, the agent's pytest children outlive the agent session. They get reparented to `launchd` (PID 1 on macOS), become PPID=1 orphans, and burn CPU forever. They never appear in any health check because the watchdog only looks at supervised processes.

This happened on 2026-06-18: the `morning-briefing` cron prompt literally contained:

```bash
uv run pytest -q -m "not slow" --no-header --tb=line -p no:cacheprovider 2>&1 | tail -10
```

The agent ran it with no `timeout` guard. Result: **~70 pytest processes running for 2+ hours**, 703.9% CPU, all PPID=1, never logged, never alerted.

The fix is three layers.

## Layer 1: patch the cron prompt (the root cause)

Find the offending prompt in `~/.hermes/cron/jobs.json`. Replace the "run pytest" section with:

```
DO NOT run pytest, jest, dotnet test, or any test command yourself.
Read the last entry of ~/.hermes/logs/health/repo-health.jsonl and summarise it verbatim.
If the file is missing or empty, report "no health snapshot yet — waiting for the next repo-health-check interval".
For git status, use plain `git -C <repo> status --short` (no test commands).
```

This is the durable fix. The other two layers are belt-and-braces.

## Layer 2: pytest-orphan-cleanup.sh (the safety net)

`~/.hermes/scripts/pytest-orphan-cleanup.sh`:

```bash
#!/bin/bash
# pytest-orphan-cleanup.sh — kills pytest processes whose PPID is 1
# (launchd-orphaned, the parent session died). Prevents the 243-pytest pile-up
# caused by the morning-briefing cron running pytest with no timeout.
#
# Idempotent: no-op if no orphans.
# Safe: leaves PID 1228 (signal_engine.daemon) alone — its argv is not "pytest".
set -u

ORPHANS=$(ps -axo pid,ppid,command 2>/dev/null | awk '$2==1 && /pytest/ {print $1}')
if [ -z "$ORPHANS" ]; then
  exit 0
fi

KILLED=0
for pid in $ORPHANS; do
  ppid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
  if [ "$ppid" = "1" ] && [ "$pid" != "1228" ]; then
    kill -9 "$pid" 2>/dev/null && KILLED=$((KILLED+1))
  fi
done

if [ "$KILLED" -gt 0 ]; then
  echo "pytest-orphan-cleanup: killed $KILLED orphan pytest process(es)"
fi
exit 0
```

The `pid != "1228"` guard is paranoia — `signal_engine.daemon` has "pytest" nowhere in its argv, but the explicit exclusion costs nothing and prevents the catastrophic mistake of killing the signal-engine daemon if someone later renames the daemon entry point to include "pytest".

## Layer 3: cron job every 5 min

```python
cronjob(action="create",
        name="pytest-orphan-cleanup",
        script="pytest-orphan-cleanup.sh",  # NOT absolute path — see note below
        schedule="every 5m",
        no_agent=True,
        deliver="local")  # never origin — silent when nothing to do
```

The `cronjob` tool requires `script` to be a filename relative to `~/.hermes/scripts/`, not an absolute path. Passing `/Users/chidionyema/.hermes/scripts/pytest-orphan-cleanup.sh` returns an error.

`deliver: local` is critical. The cleanup script is silent when no orphans exist. `origin` would page Chidi every 5 min for nothing.

## Verification

```bash
# 1) Count current orphans before cleanup
ps -axo pid,ppid,command 2>/dev/null | awk '$2==1 && /pytest/' | wc -l

# 2) Run cleanup manually
bash ~/.hermes/scripts/pytest-orphan-cleanup.sh
echo "exit=$?"

# 3) Confirm zero orphans after
ps -axo pid,ppid,command 2>/dev/null | awk '$2==1 && /pytest/' | wc -l   # expect 0

# 4) Confirm signal-engine daemon still alive
ps -eo pid,etime,command 2>/dev/null | grep signal_engine.daemon | grep -v grep
```

## Why this matters (the dropped-ball pattern)

This is a textbook dropped ball:
- A cron prompt told the LLM to run pytest with no timeout.
- The cron fired every morning. Each fire spawned dozens of orphan pytest children.
- The cron `last_status: ok` (because the agent itself exited 0; the children outlived it).
- The watchdog didn't see the children (it only watches the signal-engine daemon).
- Chidi noticed only because his CPU was at 703% and his fans were screaming.

The user's verbatim correction: *"We are fire fighting instead of addressing root cause."* This pattern's root cause is **LLM-driven crons spawning unbounded subprocesses**. The fix is structural (prompt rewrite + cleanup cron), not a watchdog band-aid.

## Related

- `references/cron-budget-subprocess-pattern.md` — the original bounded-timeout pattern (per-handler timeout, result cache). The pytest-orphan pattern complements it: bounded-timeout prevents the per-call blowup; orphan-cleanup handles the case where a subprocess outlives its parent anyway.
- `dropped-ball-prevention` SKILL.md, anti-pattern row "Cron prompts the LLM agent to run `pytest`..." — the at-a-glance reference.