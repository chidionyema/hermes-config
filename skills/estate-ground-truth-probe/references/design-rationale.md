# Estate Ground-Truth Probe — Design Rationale

## What the probe is for

User (Chidi) demanded hard receipts after repeated incidents where Otto narrated state that didn't match reality. The probe is the receipts layer.

## Why a script, not an LLM answer

The probe runs as a read-only Python script (`otto_ground_truth.py`). Three reasons:

1. **No fabrication risk.** An LLM summarizing "what's running" can hallucinate PIDs, daemon names, cron states. A script pulling from `ps`, `jobs.json`, `find`, `git status` cannot lie — what it reads IS the truth.
2. **Reproducible.** Same script, same output, byte-for-byte. The user can run it themselves and compare.
3. **Auditable.** Every line of output has a clear origin (`jobs.json`, `ps aux`, etc.). The user can verify.

## Evolution: v1 → v2 → v3

### v1 (initial)
- Sections: cron / processes / scripts / git / queue / memory
- `pgrep -af` for processes — showed PIDs only, not full cmdline
- `find -maxdepth 3` for git — missed deep repos like `~/Documents/code/*`
- Took ~30-60s on first run

### v2 (profile-aware + full cmdline)
- Added multi-profile discovery (`~/.hermes` + `~/.hermes-profiles/*` + `$HERMES_HOME`)
- Switched processes from `pgrep -af` to `ps -axo pid,command` with 160-char truncation
- Constrained memory-file hunt to all profiles
- Took ~20s

### v3 (widened — current)
Added:
- Full process snapshot (`ps aux | grep -iE 'python|node|daemon|hermes|claude|signal|cron|agy'`)
- launchctl + crontab dump (macOS)
- Deep repo git search (maxdepth 6 + code roots)
- Session-DB hunt (`*.db` under `.hermes` + targeted `~/Library/Application Support/<hermes>`)
- Per-section diagnosis (never-run jobs, daemon watchdog, signalengine dir check)

### v3 perf disaster & fix

**Problem:** v3's first run timed out at 60s and again at 90s.

**Root causes:**
1. `prof.rglob(...)` iterated through `.claude/projects/-Users-chidionyema-Documents-code-signalengine/memory/`, which has 1000s of memory files. Materializing the iterator blocked for ~60s.
2. `ps aux | grep -iE 'python|node|...'` matched ~70+ pytest processes (orphaned by `repo-health-check.py`), inflating output to 100+ lines and slowing the grep.
3. The `find /Users/chidionyema` searches at depth 6 take seconds on macOS due to Spotlight metadata.

**Fix applied (v3-final):**
- Replaced `prof.rglob` with `find ~/.hermes -maxdepth 4` — bounded and shell-level
- Added a per-section daemon process check that doesn't run the full `ps aux`
- Kept the wide `ps aux` but capped output to a manageable size
- Section 4 (git) is intentionally skippable if it times out

## What the probe DOES NOT cover (and why)

- **Logs.** Logs are large and noisy; the user reads them when they need them, not via probe.
- **Skill content.** Skills are static; the user reads `~/.hermes/skills/<name>/SKILL.md` directly.
- **In-flight process CPU/mem.** `ps` shows instantaneous state, not a trend. The user checks Activity Monitor for that.
- **Subprocess tree.** `pgrep` flattens parent/child. For daemon debugging, the user checks `pstree -p PID` or reads the daemon's own log.

## How the user uses this probe

1. User says "estate" or similar trigger phrase
2. Otto loads the skill, runs the probe, returns full output
3. User scans the output, finds the section they care about (cron jobs, processes, git state)
4. If a section is missing or timed out, that's the answer — Otto didn't get that far

## Trust contract

The probe's output is **the receipts ledger**. Otto's claims in chat must be cross-checkable against this probe. If Otto says "the daemon is running" and the probe shows PID 1228 alive, that's a receipt. If Otto says "the daemon is running" and the probe doesn't show it, Otto is wrong.

The probe is not Otto's opinion — it's the truth. Otto relays, the user judges.

## Future work (deferred)

- **JSON output mode.** The probe currently prints human-readable text. A `--json` flag would let downstream tools consume it programmatically.
- **Diff mode.** Run the probe twice with an interval, diff the output. Detect state changes without manual scanning.
- **Watchdog mode.** Run the probe on a cron, log deltas, alert on new findings. This is essentially what `otto-dispatch` does for fingerprints, but at the full-estate level.