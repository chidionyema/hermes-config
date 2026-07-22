---
name: estate-ground-truth-probe
description: When the user asks for "estate", "estate state", "estate audit", "ground truth", "what's actually running", "real state", "actual state", "probe the estate", "dump your state", or "what's the state" — run the bundled ground-truth probe and return its full stdout verbatim. Do NOT interpret, summarize, or narrate. The probe IS the answer. Read-only; no LLM; no mutation.
---

# Estate Ground-Truth Probe

## When to load this skill

Trigger phrases (verbatim or close):
- "estate" / "estate state" / "estate audit"
- "ground truth" / "what's actually running" / "real state" / "actual state"
- "probe the estate" / "dump the state" / "what's the state"
- "internal state dump" / "self audit"
- **"morning briefing" / "health check" / "repo health" / "what's the project status"** — the daily briefing's Project Health + Self-Improvement Status sections are ground-truth queries. Use this probe; do NOT read raw `repo-health.jsonl` / `metrics.jsonl` and narrate the numbers. The probe cross-references everything and reports real disk state, not what the cron said.

Also load when user says "give me the dump", "show me everything", "no narration, just facts", or expresses distrust of agent self-reports. The skill exists BECAUSE narration has repeatedly been wrong.

## What to do

1. Run: `python3 ~/.hermes/skills/estate-ground-truth-probe/otto_ground_truth.py > /tmp/estate-probe.txt 2>&1` (redirect to file to avoid notification truncation — see pitfall 14)
2. Then `read_file('/tmp/estate-probe.txt')` and return the ENTIRE stdout verbatim, inside a fenced code block so it's easy to scroll.
3. Do not summarize. Do not interpret. Do not claim "everything looks fine" or "X is broken" based on the output — the user interprets it themselves.
4. After the verbatim output, you MAY add a 1-2 line "honest gaps" footer noting what the probe did NOT cover (e.g. if it timed out, if a section errored, if you suspect staleness).
5. **For morning briefings specifically:** also read `tail -1 ~/.hermes/logs/health/repo-health.jsonl`, `tail -5 ~/.hermes/meta/metrics.jsonl`, and `ls -lat ~/.hermes/logs/reflection/ | head -3` and append a "Cron-reported health snapshot" sub-block — but label it as CRON-REPORTED, not ground truth (see pitfall 15).

## What the probe covers

- Profile discovery (all `~/.hermes*` dirs, `~/.hermes-profiles/*`, env `$HERMES_HOME`)
- Cron job state per profile (real `last_status` / `last_run_at` from `jobs.json`, NOT self-report)
- Origin-delivery list (which jobs page the user directly)
- Non-ok count
- Running processes via `ps -axo pid,command` with full cmdline
- Scripts inventory per profile (size + mtime)
- Git state across `find -maxdepth 3` for repos (branch + uncommitted count)
- Hook / queue substrate state (`/otto/hook`, `~/.hermes/queue/`)
- Memory store files (MEMORY.md / USER.md / SOUL.md)

## Pitfalls — lessons that BIT during the design of this probe

1. **`pgrep -af` without full-cmdline echo is misleading.** Showing only PIDs (e.g. "5 claude processes") gives the user nothing. Always use `ps -axo pid,command` and truncate to 160 chars so the user sees WHAT is running, not just that something matched.

2. **`ps aux | grep <term>` matches itself.** Always pipe through `grep -v -e grep -e <probe-script-name>`. The v1 probe showed 5 claude PIDs that turned out to be `pgrep` itself.

3. **`sqlite3` import errors silently break a section.** If a section tries `import sqlite3` for session-DB discovery but the module is unavailable, the WHOLE probe should not fail — wrap each section in try/except and print "unreadable: <err>" so partial data is still returned.

4. **`find -maxdepth 3` misses `~/Documents/code/*` repos.** `Documents/code/signalengine` is at depth 5. If the user wants supervised repos, the probe needs `find -maxdepth 6` OR a curated list. v2 keeps -maxdepth 3 for speed and reports this gap honestly in the footer.

5. **`HERMES_HOME` may not be set.** Discover profiles by globbing for `cron/` + `config.yaml` under `~`, not by reading `$HERMES_HOME`. Always enumerate `~/.hermes` (default) PLUS `~/.hermes-profiles/*` PLUS env override.

6. **Probe timeouts are findings, not failures.** If the probe hits a timeout, report which section timed out — don't substitute a narrative. The user interprets; you report.

7. **Don't trust `last_status` for failing crons.** The probe reports raw `last_status` from `jobs.json`. Many crons self-certify as `ok` even when they hit errors. The user cross-references the probe against their own notification history.

8. **`deliver: origin` count is what causes noise.** This is the count of crons that page the user directly. Always list them. Earlier Otto audits claimed "only otto-dispatch is origin" — wrong by 9x. The probe is the truth.

9. **Memory files may not exist on disk.** MEMORY.md / USER.md only exist as system-prompt injection in the chat. SOUL.md persists. Report what's actually on disk, not what's in your prompt.

10. **The probe MUST finish in ≤60s or it gets killed.** v1 took 60s+ and was killed by Hermes timeout. v2 (fast) takes ~20s. v3 with deep git + ps aux takes 60-90s on a busy Mac. The v3 fix: replace Python `Path.rglob` with `find ... -maxdepth 4` (avoid iterating 1000s of `.claude/projects/*/memory/` files).

11. **`prof.rglob` is a TRAP when `.claude` or `.codex` are in the profile list.** They have millions of memory files. ANY iteration over them blocks for ~60s. Always filter profiles to `~/.hermes`-only before `rglob`, OR use bounded `find -maxdepth N`.

12. **`ps aux | grep -iE 'python|node|...'` can return 70+ lines on a busy Mac** when there are orphaned pytest/test processes (from `repo-health-check.py` cron). The probe should still print them — they're real findings — but truncate the section with `head -50` to avoid dominating the output.

13. **Probe must run in background via `terminal(background=true, notify_on_complete=true)` not foreground.** A 90s probe in foreground triggers Hermes' 60s timeout, killing the probe mid-section. Background + poll = reliable.

14. **Background notification truncates the probe output to ~1900 chars (last N chars).** The `notify_on_complete` notification only shows the final ~1927 chars of stdout — sections 1-3 are invisible. **Workaround (2026-06-21): redirect to file then read_file.** Run `python3 ~/.hermes/skills/estate-ground-truth-probe/otto_ground_truth.py > /tmp/estate-probe.txt 2>&1` in foreground (it finishes in 10-15s when the probe is fast), then `read_file('/tmp/estate-probe.txt')` to get the full 200-250 line, 50KB output. Do NOT run background if you need all sections — the truncation is unavoidable in notification delivery. If the probe is slow (90s+), run background + file redirect: `terminal(background=true, command='... > /tmp/estate-probe.txt 2>&1', notify_on_complete=true)` — but be aware you'll only get the tail in the notification. The file is the ground truth.

15. **`repo-health.jsonl` can be a stale steady-state, not live signal.** (Added 2026-07-11.) The cron that writes it reads repo paths from `HERMES_CODE_DIR` (default `~/Documents/code`). If the path doesn't exist OR git returns "Operation not permitted" for sandboxed dirs, the script still writes a `state: dirty` line — same shape as real dirt. On 2026-07-11 all three repos reported `dirty (2 uncommitted)` for 28h+ straight, then manual `git status` against the real paths (e.g. `~/code-backup/lux`) returned "not a git repository". **The probe must independently git-probe each repo with `git -C <real-path> status --short` and report "unverified" rather than trusting the cron JSONL.** Until `repo-health-check.py` is fixed, treat cron-reported `dirty` as a signal to investigate, not as ground truth.

16. **`HERMES_CODE_DIR` and `HERMES_HOME` env vars are the contract, not defaults.** (Added 2026-07-11.) Same bug class as the 2026-06-23 `daily_reflection.py` hardcoded `~/Documents/code/.hermes/OBJECTIVES.md` fix — scripts that hardcode `Path.home() / "Documents" / "code"` will silently no-op or fail in sandboxed environments where that dir is unreadable. Any probe-section that iterates repos MUST: (a) read `$HERMES_CODE_DIR` first, (b) fall back to `Path.home() / "code"` and `~/code-backup`, (c) report `unverified` (not `dirty`/`pass`) when neither path resolves to a real git repo. Future extension: bake this into the probe as Section 9 ("Code-dir path resolution audit").

## Failure modes

- If the probe errors, return the error verbatim. Don't substitute your own interpretation.
- If a section times out, that's a finding — surface it as "Section N timed out" not "all looks fine."
- If jobs.json is missing or malformed, that's a finding — report it, don't paper over it.

## Implementation pitfalls (learned the hard way, 2026-06-18)

When extending this probe or building similar read-only state probes, the following macOS-specific and concurrency-specific traps bit during the v2→v3 rewrite:

### `-xdev` breaks `find` on macOS with APFS + cross-device dirs
`-xdev` (stay on one filesystem) caused the section 4 repo hunt to return 0 results because APFS firmlinks + multiple volumes under `~` made `find` abort. **Drop `-xdev` and rely on `-maxdepth` for bounded traversal.** Only re-add `-xdev` if you can prove the user's home is single-volume.

### `-prune` on `.git` makes find return 0
`find ... -name .git -type d -prune` correctly avoids recursing INTO `.git` dirs but ALSO makes find stop listing matches in the same invocation when ordered wrong. **Don't combine `-name .git -prune` with the same `-name .git` predicate as a filter.** Use one find for `.git` discovery, separate git calls for state.

### Parallel `find` per root > single sequential find
Serial `find` over `~`, `~/code`, `~/code-backup`, `~/Documents` (the last especially slow on macOS due to Time Machine snapshots) eats 90+ seconds on a real laptop. **Run each root's `find` in its own ThreadPoolExecutor worker with per-root timeout (8-12s).** One slow root can't starve the others. Same for per-repo git state — 8-way parallel `git -C ... status` instead of serial.

### Section timeouts must be aggressive
Default `run()` timeout of 25s per shell call is too generous. A single slow `find` over `~/Library` will eat the budget. **Default per-call timeout: 10s.** Tighten further for sub-section commands (`8s` for DB find, `5s` for individual `git` calls inside the ThreadPool).

### DB hunt should skip `.claude` and `.codex` dirs
`~/.claude/projects/<...>/memory/` and `~/.codex/...` contain millions of files. `Path.rglob('*.db')` over these dirs hangs the probe. **Constrain DB search roots to `~/.hermes` and explicit `~/Library/Application Support/<app>` dirs.** Never `rglob` a profile dir without an explicit profile list.

### Parallel sqlite opens with per-DB timeout
N sequential `sqlite3.connect(...).execute(...)` is slow even when each DB is fast. **Use ThreadPoolExecutor(max_workers=8) and `sqlite3.connect(timeout=3)`** — any DB that hangs the read won't stall the whole section.

### Process name regex needs to match the daemon's argv, not its friendly name
`pgrep -f signal-engine` matched ~70 pytest processes spawned by the morning-briefing cron because `signal-engine` appeared in some sub-arguments. **Match on the argv stem exactly (`signal_engine.daemon`) and ALWAYS `grep -v grep` to exclude the probe's own pgrep subprocess.** Section 2 of the probe uses `ps aux | grep -E 'signal.engine|signal_engine' | grep -v grep` and explicitly verifies the daemon PID is still alive.

## Why this skill exists

User explicitly demanded ground truth on the estate after repeated balls-dropped incidents where Otto narrated state that didn't match reality. The probe is read-only and pulls from disk/process tables directly. It cannot lie.
User explicitly demanded ground truth on the estate after repeated balls-dropped incidents where Otto narrated state that didn't match reality. The probe is read-only and pulls from disk/process tables directly. It cannot lie.

User's exact words that drove the design:
- "No narration, evidence only"
- "Fix the root cause and prove it"
- "Where is the evidence? Another dropped ball"
- "Don't forward, investigate"
- "Save this and anytime I ask you for estate then run it and return result"

## Companion files

- `otto_ground_truth.py` — the probe itself (read-only, no LLM, no mutation)
- `references/design-rationale.md` — why each section exists, what was tried and rejected