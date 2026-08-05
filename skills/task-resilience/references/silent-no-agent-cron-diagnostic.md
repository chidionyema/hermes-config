# Silent `no_agent` Cron Diagnostic

## Symptom

A `no_agent=true` cron job is enabled, has a valid schedule, and a
script that runs fine when invoked manually — but `last_run_at` is
`null` in `~/.hermes/cron/jobs.json`. The scheduler appears not to
fire it. Other jobs from the same era have `last_run_at` populated.

This is distinct from "cron fires but errors" (where `last_status`
is set and `last_error` is populated) and from "cron is gated by
OFF_SWITCH" (which logs "DISARMED" but still bumps `last_run_at`).

## The 4-Step Probe

### 1. Confirm the script works manually

Run the exact command the scheduler would invoke, from the scheduler's
working directory:

```bash
# Default scheduler cwd = ~/.hermes/scripts/ (the script's parent).
# If you see relative paths in the script like "python3 scripts/X.py",
# those resolve from ~/.hermes, NOT from ~/.hermes/scripts/.
cd ~/.hermes/scripts && python3 <script_basename> [args]
cd ~/.hermes && python3 scripts/<script_basename> [args]
```

A manual run that exits 0 confirms the script itself isn't the
problem. The bug is upstream of the script.

### 2. Inspect `jobs.json` for the job's entry shape

```bash
jq '.jobs[] | select(.id=="<job-id>") | {created_at, last_run_at, last_status, enabled, state, no_agent, script, workdir}' \
   ~/.hermes/cron/jobs.json
```

Compare to a working peer job. If `last_run_at` is `null` and the
peer is populated, the scheduler has never picked this job up.

### 3. Read `_run_job_script` in `~/.hermes/hermes-agent/cron/scheduler.py`

Lines ~892–1004 define how the scheduler builds the subprocess argv.
Key facts to verify:

- The scheduler **strips args from the script field**. A job whose
  `script` is `"python3 scripts/self_improve_runner.py --hourly"` is
  invoked as `[python3, <abs_path_to_script>]` — the `--hourly` flag
  is dropped. If the script defaults to hourly mode when no flag is
  given, fine. Otherwise the script needs to be invoked without the
  flag, or the scheduler needs a fix.
- The scheduler runs the subprocess with
  `cwd=str(path.parent)`. That's `~/.hermes/scripts/`, NOT `~/.hermes/`.
  So `python3 scripts/foo.py` in the script field resolves correctly
  (path = `scripts/foo.py`, then `Path(script_path)` is made absolute
  as `~/.hermes/scripts/scripts/foo.py` — which is wrong if the
  field starts with `scripts/`).
- `workdir: null` means the subprocess inherits the scheduler's cwd.
  If the scheduler was launched from `~/`, all scripts run from `~/`
  and `scripts/foo.py` fails to resolve.

### 4. Check whether the job is even in the scheduler's in-memory registry

The on-disk `jobs.json` may have the entry, but the scheduler process
might be running with a stale in-memory copy loaded before the entry
was added (e.g. job added at 09:30, scheduler tick started at 09:00
and is still alive). `last_run_at` stays `null` until the scheduler
process restarts and re-reads `jobs.json`.

Symptom: `jobs.json` shows `created_at: <recent>` and `enabled: true`
but `last_run_at: null`. Other jobs from the same era show
`last_run_at` populated. → The scheduler needs a restart to pick up
the new entry, OR the scheduler has a hot-reload bug that doesn't
fire on entries added mid-tick.

**Fixes (in order of preference):**

1. Restart the cron scheduler process so it reloads `jobs.json` from
   disk.
2. If the scheduler is supposed to hot-reload, fix that defect — the
   bug is that new entries are never picked up until restart.
3. If `workdir: null` is the bug (script needs `cd ~/.hermes` first),
   set `workdir: "/Users/chidionyema/.hermes"` on the job via the
   `cronjob` tool's `update` action.

## Recipe from the 2026-08-04 RSI Audit

```text
self-improve-hourly (job id) — created 2026-08-03T09:30:00Z
  schedule: 0 * * * *  (Hourly)
  script:   python3 scripts/self_improve_runner.py --hourly
  workdir:  null
  enabled:  true
  state:    scheduled
  last_run_at: null  ← scheduler never fired it
  last_status:  null

Manual probe:
  $ cd ~/.hermes && python3 scripts/self_improve_runner.py --hourly
    Cycle: 6 gaps, 0 closed, 0 shadow
    velocity -0.1185 📉, health 0.213
    Complete (0.76s)              ← script works

  $ cd ~/.hermes/scripts && python3 self_improve_runner.py
    Cycle: 6 gaps, 0 closed
    Complete (0.42s)              ← also works (defaults to hourly)
```

The script works in both cwd candidates. The argv-stripping in
`_run_job_script` would also be fine because the script defaults to
hourly. So the bug is upstream of the script — most likely the
scheduler process loaded `jobs.json` before this entry existed
(`created_at: 2026-08-03T09:30:00Z` is recent enough that this is
plausible if the scheduler tick started earlier and hasn't been
restarted).

**Action:** confirm scheduler PID, restart it, watch `last_run_at`
populate on the next hourly tick.

## What This Skill Does NOT Cover

- Crons that fire but error → look at `last_error` field, fix the
  script
- Crons that fire but the prompt is wrong → fix the `prompt` field
- Crons blocked by `OFF_SWITCH` → check `~/.hermes/meta/OFF_SWITCH`
  presence
- Gateway-down masquerading as "cron is broken" → see
  `dropped-ball-prevention` "Gateway-down masquerades as cron is broken"