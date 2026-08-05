# CI Watchdog Pattern

Reusable recipe for cron-driven CI failure monitoring. Built 2026-08-02 to
replace reactive triage with automated surface-to-user.

## Pattern: probe → digest → silent-on-healthy → deliver-on-signal

Every watchdog script follows the same contract:

1. **Probe** — collect ground truth (gh CLI, git, curl, API)
2. **Digest** — SHA-256 of deltas. Compare against previous.
3. **Silence** — exit 0, stdout empty = healthy AND unchanged
4. **Deliver** — non-empty stdout → bash wrapper calls `hermes send --to telegram`

## Components

### ci-watchdog.py (the probe — substance)

Lives at `~/.hermes/scripts/ci-watchdog.py`.

**What it checks:**
- 4 tracked repos: Prospector, Signal Engine, Haworks, TIE
- Each repo: latest GitHub Actions run status via `gh run list --json`
- Falls back to local git state (dirty count, commit age) if `gh` CLI unavailable
- Skips repos without `.github/workflows/` (except TIE)

**Output format (on failure):**
```
🔴 *CI watchdog — regressions found*

🔴 *Prospector* · CI `failure` · 6h ago
   `main` · #30743068322
   Run: https://github.com/chidionyema/prospector/actions/runs/30743068322
   local: dirty(11) · sha `33b038e`
```

**Output format (healthy):**
```
✅ CI watchdog: 4 repos healthy (1d555a5f86ac)
```

### ci-watchdog.sh (bash wrapper — delivery)

Lives at `~/.hermes/scripts/ci-watchdog.sh`. Hard-timeout the probe at 30s.
Guard before `hermes send`: `[ -z "$output" ] && exit 0`. Never deliver empty
messages.

### Cron registration

```
cronjob action='create' name='ci-watchdog-daily' no_agent=True \
  schedule='0 7 * * *' script='ci-watchdog.sh'
```

Job ID: `b38b298aea62`. Runs at 07:00 daily, delivers to origin.

## Adding a new repo

1. Add entry to `REPOS` dict in `ci-watchdog.py`
2. Add `.github/workflows/` path to `SKIP_IF_MISSING_WORKFLOW` if needed
3. Re-run the probe: `python3 ~/.hermes/scripts/ci-watchdog.py`
4. Confirm the new repo appears in deltas and digest rolls

## Gotchas

### `gh run list --json` requires authenticated gh CLI

The probe calls `gh run list` from each repo's working directory. If `gh` is
not authenticated or the token is expired, fallback is local git state only
(no run ID, no URL). The probe gracefully degrades — logs `gh CLI unavailable`
in deltas rather than crashing.

### `hermes send` prints "Sent to telegram" even when stdin is empty

Always guard the bash wrapper: `[ -z "$output" ] && exit 0` BEFORE calling
`hermes send`. Otherwise every silent tick logs a false "Sent" line.

### Digest-based silence works across runs, not across reboots

The digest file at `~/.hermes/cache/ci-watchdog/ci-digest.txt` persists. If
the probe detects a status change (e.g., a new CI failure), the digest will
differ and the user gets a delivery. If no repos change status between runs,
silent.

## Related

- `references/goal-ping-pattern.md` — the WRONG pattern (asking questions
  via cron) and the replacement (watchdog that does work)
- `references/probe-contract.md` — the 6-property spec every probe must satisfy
- `references/output-dedup-and-state-mirroring.md` — digest dedup pattern
  in detail
