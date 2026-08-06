---
name: recurring-briefing
description: Recurring scheduled narrative briefings — morning briefings, end-of-day reports, weekly rollups, post-incident summaries, and PDD-flavored daily activity ledgers (functions modified, specs verified, regressions blocked, new specs). Aggregates disk artifacts (health JSONL, watchdog alerts, gap-finding reports, daily reflections, OBJECTIVES, cron state, LUX proving-ground/receipts) into a single structured human-readable report. Read-only by design — runs no tests, dispatches no agents, performs no mutations. Load when the user asks for "morning briefing", "what's the state of things", "give me the daily", "end of day report", "summarize today's activity", "what did we build today", "what functions were modified", or when a cron job is scheduled to deliver a periodic status report.
version: 1.1.0
author: Otto
metadata:
  hermes:
    tags: [briefing, scheduled, recurring, cron, daily, weekly, status-report, synthesis, probe]
    related_skills: [estate-ground-truth-probe, estate-management, project-health-audit, task-resilience]
prerequisites:
  files:
    - ~/.hermes/logs/health/repo-health.jsonl   # repo health snapshots
    - ~/.hermes/logs/maintenance/gap-finding-*.md
    - ~/.hermes/logs/maintenance/near-miss-*.json
    - ~/.hermes/logs/reflection/YYYY-MM-DD.md
    - ~/.hermes/meta/change-outcomes.jsonl
    - ~/.hermes/meta/metrics.jsonl
    - ~/.hermes/OBJECTIVES.md
    - ~/.hermes/task-state/current_task.json
    - ~/.hermes/reports/estate-optimization.md
    - ~/.hermes/logs/alerts/watchdog.jsonl
---

# Recurring Briefing — Read-Only Narrative Synthesis

A recurring briefing is a **scheduled cron job** (or on-demand request) that produces a single human-readable report by **reading disk artifacts** and assembling them into a structured narrative. It runs no tests, dispatches no agents, and performs no mutations. Its only side effect is the report itself.

The class includes: morning briefings, end-of-day reports, weekly rollups, post-deploy summaries, post-incident digests, and any "give me the state of things" request that pulls from many subsystems.

## Core Principle: Probe-as-Answer, Not Narrative-from-Memory

The briefing is a **probe**, not a narration. The agent reads files and pastes excerpts; the agent does NOT remember or summarize. The user's correction history is explicit: narrated state has repeatedly been wrong, while disk-read state has repeatedly been right.

**Two non-negotiable rules:**

1. **NEVER run tests.** No `pytest`, no `jest`, no `dotnet test`, no `npm test`. The briefing is a read-only synthesis. The cron that runs the briefing is almost certainly already past the time budget; spawning a 30-second test suite will time out the job.
2. **NEVER use `read_file` followed by a `terminal` test command.** If you find yourself about to run a test, stop — the briefing doesn't need it. Read the health JSONL snapshot instead.

## When to Use

- A cron job is scheduled to deliver a periodic report (e.g. 9am morning briefing)
- The user says "morning briefing", "daily status", "end of day", "weekly rollup", "where are we", "give me the state of things"
- The user asks for a status report that should aggregate many subsystems
- A post-incident digest is needed (after a known failure, surface the cluster of related findings)

## When NOT to Use

- The user wants a one-off deep audit — use `project-health-audit` or `hermes-self-audit`
- The user wants a single subsystem's state (cron, repo, etc.) — use the relevant narrow skill
- The user asks "is X working?" where X is one specific thing — just probe X, don't aggregate
- The user wants recommendations and action — that's `estate-management` Phase 3 (optimization) or strategist-audit, not a briefing

## The Briefing Workflow

### Step 1 — Read the artifacts

All read-only. All `read_file`, `tail`, `head`. No tests, no `find` over large trees.

**Project health** (latest entry verbatim):
```bash
tail -1 ~/.hermes/logs/health/repo-health.jsonl
```

**Self-improvement state**:
```bash
# Latest gap-finding
ls -t ~/.hermes/logs/maintenance/gap-finding-*.md | head -1
# Latest near-miss
ls -t ~/.hermes/logs/maintenance/near-miss-*.json | head -1
# Yesterday's self-reflection (or last available)
ls -t ~/.hermes/logs/reflection/*.md | head -1
# Meta-improver outcomes
tail -3 ~/.hermes/meta/change-outcomes.jsonl
# Velocity trend
tail -3 ~/.hermes/meta/metrics.jsonl
```

**Cron health** (real state, not self-report):
```bash
hermes cron list | grep -B2 "error:" | head -30
```

**Watchdog alerts** (open ones, not historical):
```bash
tail -10 ~/.hermes/logs/alerts/watchdog.jsonl
```

**Active objectives + interrupted tasks**:
```bash
cat ~/.hermes/OBJECTIVES.md
cat ~/.hermes/task-state/current_task.json
```

**Estate optimization** (the 6am pipeline output):
```bash
cat ~/.hermes/reports/estate-optimization.md 2>/dev/null
```

### Step 2 — Cross-reference cron `last_status` against disk artifacts

**This is the briefing's unique value-add.** A cron reporting `last_status: ok` does NOT mean it actually ran successfully. The briefing is the place where disk state and cron state are reconciled.

Common false-`ok` patterns the briefing must catch:

| Cron name | Reports `ok` when... | Real signal is in... |
|-----------|----------------------|----------------------|
| `daily-self-reflection` | `daily_reflection.py` exits 0 | `ls -t ~/.hermes/logs/reflection/ \| head -1` — if oldest is >1 day, the reflection is broken |
| `daily-strategist-audit` | Cron dispatches and the script returns | `ls -t ~/.hermes/reports/strategist-audit-*.md \| head -1` — if missing for today, the audit crashed mid-write |
| `morning-briefing` | Job finishes within timeout | Did the report actually get delivered? The cron can succeed but deliver a truncated/empty response |
| `health-watchdog` | exits 0 or 1 (intentional) | `tail -5 ~/.hermes/logs/alerts/watchdog.jsonl` — if watchdog itself is broken, the absence of alerts is silent |
| `idle-continuous-learning` | Script ran | `cat ~/.hermes/logs/maintenance/idle-learning-runs.jsonl \| tail -3` — the run log distinguishes `Complete` from `preempted` |

### Step 3 — Surface interrupted work

Always check `~/.hermes/task-state/current_task.json` for `interrupted: true`. If an interrupted task exists from earlier in the day, it is a P0 finding for the briefing — work was started and not completed.

```bash
cat ~/.hermes/task-state/current_task.json
```

If `interrupted: true`:
- Report the task description verbatim
- Note `tool_calls_completed` (likely 0 if interrupted before any work)
- Cross-reference with the cron that should have done the work (e.g. a 7am interrupted strategist audit = the `daily-strategist-audit` cron did not complete)
- Surface as the FIRST item under "What are today's priorities?"

### Step 4 — Format the report

The structured output shape that morning briefings must follow (and other recurring briefings should adapt):

```
**Morning Briefing — [date]**

**Yesterday:**
- [bullet: project work done]
- [bullet: what the previous reflection proposed]
- [bullet: whether those items got done]

**Self-Improvement Health:**
- Domain coverage: [X]% (change: +/-)
- Untriggered policies: [N]
- Uncovered domains: [N]
- Outcome velocity: [N pending, N determined]

**Project Health:** (verbatim from health JSONL)
- Signal: [state] ([summary])
- LUX: [state] ([summary])
- Prospector: [state] ([summary])

**Cron health (active issues):** (from real `last_status` cross-ref)
- 🔴 [broken cron] — [error type and last attempt]
- 🟡 [degraded cron] — [what's missing]

**Watchdog alerts:** [N] open fingerprints

**Carry-over from yesterday:** [open improvement items still on disk]

**What are today's priorities?**
1. [highest-leverage action]
2. ...
```

Key formatting rules:
- **Section headers in bold, content in bullets.** No prose paragraphs in briefing sections.
- **Verbatim JSON for `repo-health.jsonl`** — paste the raw line, don't paraphrase "all three repos are dirty."
- **Each finding cites the file and line** when possible. `~/.hermes/meta/change-outcomes.jsonl` last entry, `~/.hermes/logs/reflection/2026-06-24.md` line 35, etc.
- **Priorities are 1-3-5, not 1-10.** If the list is longer than 5, the briefing failed to triage.

### Step 5 — Deliver, don't interpret

The briefing is delivered as the final response. Do not:
- Add "let me know if you want me to act on any of these"
- Add "want me to fix X?" (the user will say so if they want it)
- Add commentary about the briefing itself ("this report covers...")

The only valid post-content note is a 1-2 line "honest gaps" footer listing what the briefing did NOT cover (e.g. "active crons not surveyed: 16; only errored ones listed").

### Step 5b — PDD Activity Ledger (when the cron asks "what was built today?")

Some scheduled briefings ask specifically about **PDD-shaped activity**: which functions were modified, which specs were verified, which regressions were blocked, which new specs were created. This is a read-only synthesis too — it draws on **disk artifacts**, never on `git log` queries inside sandboxed project directories.

**The four axes and their canonical disk sources:**

| Axis | Disk source | What to extract |
|---|---|---|
| Functions modified | `git diff --stat` is unavailable when projects are sandboxed; fall back to **proving-ground entries** (each `verify` action names the target function) and **session_search with `query=<fn-name>`** to find tool calls that edited code | Function names that appeared in today's proving-ground receipts |
| Specs verified | `~/.lux/receipts/<date>.jsonl` — filter `action: "verify"` | `target` (spec name) + `proof.verdict` (PASS/FAIL) + `proof.passed / proof.total` |
| Regressions blocked | `~/.lux/receipts/<date>.jsonl` — filter `action: "verify"` AND `proof.verdict: "FAIL"` | The failing target + clause count + first failing clause name if present |
| New specs created | `~/.lux/specs/*.json` files with mtime >= today, AND `~/.lux/receipts/<date>.jsonl` filtered `action: "spec_create"` | Spec name + function name + creation timestamp |

**Procedure:**

```bash
# 1. Today’s proving-ground log (what the auditor attempted)
ls -la ~/.lux/proving-ground/$(date +%Y-%m-%d).jsonl 2>/dev/null

# 2. Today’s POPDD receipts (what actually signed through verification)
test -f ~/.lux/receipts/$(date +%Y-%m-%d).jsonl \
  && jq -r 'select(.action=="verify") | "\(.target) \(.proof.verdict) \(.proof.passed)/\(.proof.total)"' \
       ~/.lux/receipts/$(date +%Y-%m-%d).jsonl

# 3. New specs created today
find ~/.lux/specs -name '*.json' -newermt "$(date +%Y-%m-%d)" 2>/dev/null

# 4. Sessions that touched code today
session_search(query="<project-name>", sort="newest", limit=5)
```

**Honest-gap footer for this style:** "Code activity surveyed via disk receipts (`~/.lux/receipts/`); direct `git log` queries inside `~/Documents/code/` were blocked by the cron sandbox — see Pitfall 14."

See `references/pdd-activity-ledger.md` for the full data-source map and worked examples.

## Pitfalls (Earned in Production)

### 1. Cron `last_status: ok` lies — always cross-reference with disk

The most expensive false-positive in recurring briefings. The 9am `morning-briefing` cron in Otto's estate reported "ok" status for 9 days while the underlying job was timing out at 936s. The actual failure was only visible in the cron `last_status` field's stderr, not the success indicator.

**Rule:** every cron "all green" finding must be backed by a disk artifact check, not the cron's self-report. The `hermes cron list | grep -B2 "error:"` is authoritative.

### 2. The cron that delivers the briefing is often the cron that needs reporting on

The 9am morning-briefing cron has been broken for 9 consecutive days in Otto's estate. The briefing is delivered by an alternate path (the cron trigger firing through a different mechanism), but the briefing itself surfaces this as a P0 finding. This is not a contradiction — it's the briefing's job to surface that its own delivery path is broken.

**Rule:** if `hermes cron list` shows `morning-briefing` (or whatever cron delivers this briefing) errored, the briefing MUST say so explicitly in the "Cron health" section. The user needs to know that future automatic deliveries will also fail.

### 3. Health JSONL "dirty" status can be steady-state noise, not real dirt

A common false signal: the repo health probe shows `signalengine: DIRTY (2 uncommitted)` for 6+ consecutive 2h checks. If the dirt is steady-state (e.g. `__pycache__` or runtime `queue/` files in `.gitignore`), reporting it as a finding every briefing is noise. Investigate ONCE: does the dirt grow, change, or stay identical? Identical + .gitignored = noise, not finding.

**Rule:** if `repo-health.jsonl` shows the same `DIRTY (N uncommitted)` for 3+ consecutive entries, the briefing should note it ONCE as "steady-state" and not re-flag it. Use `git -C <repo> status --short` to confirm the uncommitted files are not growing.

### 4. Never run tests, even for "quick verification"

The briefing instructions explicitly say "DO NOT run pytest, jest, dotnet test, or any test command yourself." This is not a stylistic preference — running `pytest -q` on a slow repo can take 60+ seconds and time out the entire cron job. The briefing is read-only, full stop.

**Rule:** if a "should I run the tests to verify X?" thought appears, the answer is no. Read the health JSONL entry instead. It contains the same information (pass/fail/dirty/skip) without the runtime cost.

### 5. Date arithmetic: "yesterday" is not always clear

In a cron-delivered morning briefing fired at 9am local time, "yesterday" can be ambiguous:
- Local time: yesterday in user's timezone
- UTC: today in UTC if local is morning (e.g. 9am BST = 8am UTC, "yesterday" in UTC is 24h earlier than local yesterday)

**Rule:** the briefing uses the **user's local timezone** for "yesterday". Verify with `date +%Y-%m-%d` which echoes local time. Use that date when reading `~/.hermes/logs/reflection/$(date +%Y-%m-%d).md` for today's reflection. For "yesterday's reflection" use `date -v-1d +%Y-%m-%d` (macOS) or `date -d yesterday +%Y-%m-%d` (Linux).

### 6. Interrupted task in `current_task.json` is always a P0 finding

If the briefing finds `interrupted: true` in `~/.hermes/task-state/current_task.json`, that's a signal that work was started but not completed. The interrupted task is always reported FIRST in the priorities section, regardless of what other items are pending.

**Rule:** `interrupted: true, tool_calls_completed: 0` indicates a crash before any work — usually a model timeout or a model provider issue. `interrupted: true, tool_calls_completed: N>0` indicates work was in progress when interrupted. The briefing should report both states distinctly.

### 7. Reflection file is "missing" when it shouldn't be

The `daily-self-reflection` cron runs at 6pm daily. If the briefing at 9am next morning finds no reflection file for the previous day, the reflection cron is broken (not just slow). Distinguish:
- `~/.hermes/logs/reflection/$(date +%Y-%m-%d).md` exists with content = today ran (rare; 6pm hasn't happened yet)
- `~/.hermes/logs/reflection/$(date -v-1d +%Y-%m-%d).md` exists = yesterday ran
- Neither exists = the reflection has been broken for >24h

**Rule:** a missing-yesterday reflection is reported in the "Cron health" section as a degraded cron, not as a "self-improvement" finding. The disk artifact is the source of truth.

### 8. Gap-finding reports can be identical for days

If `gap-finding-YYYY-MM-DD.md` is byte-identical (or near-identical) to yesterday's, that's a signal that the self-improvement loop is **starved for signal**, not producing new findings. The briefing should report this once as "pipeline flat" — not as a fresh finding every day.

**Rule:** if the gap-finding report has the same uncovered domains and same weak-coverage items for 3+ consecutive days, note "pipeline has been flat for N days" in the self-improvement section. After 7 days, escalate to a "pipeline is stalled" finding (the meta-improver needs a forcing function or the corpus needs a new source of signal).

### 9. Use `find` with timeouts in cron, or omit it

The morning briefing in Otto's estate has hit "find command timed out after 60s" when surveying repo directories. The repos are under `~/Documents/code/` at depth 5+; a naïve `find ~ -maxdepth 4` misses them. The briefing uses `ls -d ~/Documents/code/*/ 2>/dev/null` for the known set, or `ls -d ~/code/*/` if that path exists.

**Rule:** never run `find ~ -maxdepth N` in a briefing. Use the known repo path set or `ls -d` with a small scope. If a directory survey is required, use `search_files(target='files', path=<scoped>)` with a short timeout.

### 10. "I have time" thoughts lead to "I should fix this" — which is a separate cron

A morning briefing might surface that the `health-watchdog` is broken (a P0 finding). The agent may think "I have a few minutes, let me fix it." Wrong. The briefing is a deliverable, not a fix. The fix is its own cron job (`estate-auto-remediation.py` or a strategist dispatch). The briefing surfaces; the fix is dispatched separately.

**Rule:** the briefing DELIVERS findings, it does not ACT on them. Action requires either explicit user instruction ("fix the morning-briefing cron") or its own scheduled cron. The briefing can RECOMMEND a priority, but execution is a separate event.

### 11. Stream-stall + HTTP 402: the billing-rejection failure mode (added 2026-07-02)

**Symptom (matched 2026-07-02 audit):** A cron job's `last_error` field reads `TimeoutError: Cron job 'X' idle for 936s (limit 600s) — last activity: waiting for stream response (Ns, no chunks yet)`. The cron surfaces only the TimeoutError; the underlying HTTP 402 "Insufficient Balance" rejection from the LLM provider is buried in `logs/agent.log` from a separate run.

**Why it bites:** This is a billing/auth decision, not a script bug. The watchdog re-fires on the same `TimeoutError` every 15 minutes, generating hundreds of `CRON_ERROR` entries with zero resolution path. The agent hangs waiting for a stream that will never arrive.

**Detection protocol (use this BEFORE assuming the cron is broken):**

1. `cron job last_error` contains `waiting for stream response` and `no chunks yet` → stream stall signature
2. Cross-reference `logs/agent.log` for the underlying cause:
   ```bash
   grep -E "Insufficient Balance|HTTP 402|402 -" logs/agent.log | tail -3
   ```
3. If the grep hits → **CREDITS_ERROR**, not a script defect. The fix is `needs_human` (top up balance or switch default model in `~/.hermes/config.yaml`).
4. If the grep misses → real timeout. Investigate as usual.

**Watchdog classifier pattern (added 2026-07-02):** The watchdog should NOT re-fire `CRON_ERROR` every cycle for billing rejections. Emit a single `CREDITS_ERROR` fingerprint per affected job per cycle instead, with a one-time `agent.log` cross-reference. See `~/.hermes/scripts/watchdog.py` lines ~102-135 for the reference implementation. The same pattern should be applied to `401 Unauthorized`, `429 Too Many Requests`, and `Payment Required` (already covered).

**Rule:** when a recurring briefing cron (or any LLM-driven cron) surfaces only `TimeoutError` with the stream-stall signature, cross-check `agent.log` for the HTTP status code BEFORE recommending a script-level fix. Money/billing is `needs_human` — the briefing can surface it but cannot resolve it.

### 12. Gateway-exit-diag.log is the canonical source of scheduler health (added 2026-07-02)

**Symptom (matched 2026-07-02 audit):** Cron `last_run_at` says "ran 9 days ago" but `next_run_at` says "tomorrow 8am." The cron has been silent for 9 days but the gateway reports `last_status: ok` for everything that DID fire. The actual cause: the gateway was down for 7 days. No cron ticks fired during that window — daily `0 H * * *` jobs simply never woke up.

**Why `last_run_at` lies:** When the gateway is down, the cron scheduler doesn't run. `last_run_at` reflects the last successful run before the outage, not "ran today." The next scheduled run is still computed from the schedule expression, so `next_run_at` is correctly pointing at tomorrow — but the cron never fires.

**Source of truth:** `~/.hermes/logs/gateway-exit-diag.log` and `~/.hermes/logs/gateway-exit-diag.log.pre-...` rotated files. Look for the `gateway.start` entries — the gap between consecutive `gateway.start` timestamps IS the outage window. `gateway.exit_nonzero` entries within the gap explain the cause.

**Companion probe:**
```bash
# Find the longest gateway-start gap in the last 30 days
python3 -c "
import json
from datetime import datetime
starts = []
for line in open('/Users/chidionyema/.hermes/logs/gateway-exit-diag.log'):
    try:
        d = json.loads(line)
        if d.get('tag') == 'gateway.start':
            starts.append(datetime.fromisoformat(d['ts'].replace('Z','+00:00')))
    except: pass
if len(starts) > 1:
    gaps = [(starts[i+1]-starts[i]).total_seconds() for i in range(len(starts)-1)]
    print(f'Longest gap: {max(gaps)/3600:.1f}h  (avg: {sum(gaps)/len(gaps)/3600:.1f}h)')
    print(f'Total gateway restarts: {len(starts)}')
"
```

**Rule:** if a daily cron (`0 H * * *` schedule) shows `last_run_at` older than 26h AND `next_run_at` points to a future time, do NOT conclude "the cron is broken." First probe `gateway-exit-diag.log` for the gateway-uptime window. The cron is likely correct; the gateway was down.

**Sub-rule for the briefing:** when the briefing finds the daily cron silent for >48h, surface it as "Cron health: X silent for N days — gateway may have been down Y days" rather than "Cron is broken." The fix is gateway restart + cron replay, not a cron-edit.

### 14. Cron sandbox blocks `~/Documents/code/` — fall back to disk artifacts, do not declare "no activity" (added 2026-07-02)

### 13. Cron sandbox blocks `~/Documents/code/` — fall back to disk artifacts, do not declare "no activity" (added 2026-07-02)

**Symptom (matched 2026-07-02 and 2026-06-24 daily-activity crons):** A cron asks "what functions were modified today?" and `git -C ~/Documents/code/lux log --since=today` returns `Operation not permitted`. The naive response is to declare "no activity today" — but that's the **wrong** answer. The activity may have happened; the cron just can't see it.

**The fallback data set is already on disk and read-accessible from cron:**

| What the cron wants | Sandbox-blocked path | Readable disk artifact |
|---|---|---|
| Functions modified | `git diff` in project | `~/.lux/proving-ground/<date>.jsonl` (action=verify entries name targets) |
| Specs verified | project `lux spec verify` | `~/.lux/receipts/<date>.jsonl` |
| Regressions blocked | CI gate output | `~/.lux/receipts/<date>.jsonl` filter `verdict:FAIL` |
| New specs created | project `lux spec create` | `~/.lux/specs/*.json` mtime >= today |
| Today's sessions | n/a | `session_search(sort='newest')` |

**Rule:** when the briefing cannot reach `~/Documents/code/`, it must **fall back to the disk-artifact set, NOT declare "no activity."** Declare what was and wasn't observable in the honest-gaps footer: e.g. "Code activity surveyed via disk receipts; direct `git log` queries inside `~/Documents/code/` were blocked by the cron sandbox — see project-health-audit's macOS CWD sandbox reference."

**Companion pitfall in `project-health-audit`:** this skill's Pitfall #11 ("macOS sandbox CWD permission failures") covers the symptom in detail. The recurring-briefing-specific lesson is the **fallback strategy**, not the symptom — both cron types hit the same wall but report differently: `project-health-audit` lists the sandbox issue as a finding; `recurring-briefing` for a daily-activity question uses the artifact fallback and treats the sandbox as a known limitation in the honest-gaps footer.

**Why this matters:** when the cron says "summarize today's activity across all projects" and reports "nothing happened" because `git log` was blocked, that's a false negative that masks actual work. The proving-ground log is the source of truth — every `verify` action records its target function, and every `verdict:PASS|FAIL` is auditable. The cron job is read-only by design (this skill's Core Principle); the disk artifacts are read-accessible; the fallback is free.

### 15. The session DB is `state.db`, NOT `sessions.db` — and the schema gotchas (added 2026-07-05)

**Symptom (matched 2026-07-05 daily-activity cron):** A briefing tries to enumerate today's sessions via `sqlite3 ~/.hermes/sessions.db "SELECT … FROM sessions …"` and gets back **zero rows** — not because no sessions ran, but because `~/.hermes/sessions.db` is a 0-byte empty file. The real session store is `~/.hermes/state.db`.

**Verification:**
```bash
ls -la ~/.hermes/sessions.db ~/.hermes/state.db
# state.db:        several MB
# sessions.db:     0 bytes (or doesn't exist as a real table)
```

`sqlite3 ~/.hermes/sessions.db ".tables"` returns nothing. `sqlite3 ~/.hermes/state.db ".tables"` returns `sessions`, `messages`, `messages_fts`, etc. **Always use `state.db` for session/message queries.**

**Schema gotchas on `state.db` (added 2026-07-05):**

| Column you expect | Actual column on `state.db` | Gotcha |
|---|---|---|
| `messages.created_at` | `messages.timestamp` (REAL, unix epoch) | Use `datetime(timestamp, 'unixepoch')` |
| `sessions.last_active` | **does not exist** | Use `sessions.ended_at` (may be NULL while session is open) |
| `sessions.started_at` | REAL unix epoch | `datetime(started_at, 'unixepoch')` works |
| `sessions.message_count` | INTEGER | Counts tool messages too; filter `WHERE role='user'` or `'assistant'` |
| Filter by date | `timestamp >= strftime('%s', 'YYYY-MM-DD')` | `strftime('%s', ...)` returns unix epoch seconds |

**Working query templates:**
```bash
# Today's sessions
sqlite3 -header ~/.hermes/state.db \
  "SELECT id, title, source, message_count,
          datetime(started_at,'unixepoch') AS started,
          datetime(ended_at,'unixepoch') AS ended
   FROM sessions
   WHERE started_at >= strftime('%s','$(date +%Y-%m-%d)')
     AND started_at <  strftime('%s','$(date -v+1d +%Y-%m-%d 2>/dev/null || date -d tomorrow +%Y-%m-%d)')
   ORDER BY started_at;"

# Today's assistant messages (preview)
sqlite3 -header ~/.hermes/state.db \
  "SELECT substr(s.title,1,40) AS session,
          datetime(m.timestamp,'unixepoch') AS t,
          substr(m.content,1,100) AS preview
   FROM messages m JOIN sessions s ON m.session_id=s.id
   WHERE m.role='assistant'
     AND m.timestamp >= strftime('%s','$(date +%Y-%m-%d)')
   ORDER BY m.timestamp;"
```

**Bonus pattern (added 2026-07-05):** A recurring session titled `Projects Overview` (source=`telegram`) emits the heartbeat message `"Otto here — what's the goal of the moment?"` on a timer — observed 8+ times today between 08:24 and 20:12 BST. This is **recurring boilerplate, not real work**. When a daily-activity cron sees this pattern, count it once as "Otto heartbeat cycles fired" and do not weight it as substantive activity. The signal of real work is a *user reply* that triggers a non-heartbeat assistant response, or a tool-call sequence that writes files / dispatches tasks.

**Rule:** when querying session/message data in a briefing, always use `~/.hermes/state.db` (not `sessions.db`). Apply the schema gotchas above. Treat repeated identical heartbeat messages in the `Projects Overview` session as scheduler churn, not work.

### 16. `last_run_at: null` doesn't mean scheduler is down — invoke the due-job iterator (added 2026-08-04)

**Symptom (matched 2026-08-04 self-improve-hourly audit):** A registered cron job (`hermes cron list` shows `state: scheduled, enabled: true, last_run_at: null`) never fires. `last_status` is `null`, no `last_error`, no warning. The scheduler appears healthy (gateway process is alive, other jobs from the same era have `last_run_at` populated). What looks like "the cron is silently broken" is actually **one malformed job in the shared iterator crashing the dispatch loop for every job that comes after it in registration order**.

**Why `last_run_at: null` lies:** When `_get_due_jobs_locked()` (or the equivalent) walks the jobs list and hits a `schedule.get("kind")` call on a bare-string schedule, the resulting `AttributeError: 'str' object has no attribute 'get'` aborts the entire function. The surrounding tick driver's `try/except Exception as e: logger.debug("Cron tick error: %s", e)` silently swallows the error. No jobs are returned as due. The broken job AND every job that would have come after it in iteration order appear to never run.

**The tell is the schema shape.** Compare a working job entry to a broken one:
```bash
# Working job — full schema
jq '.jobs[] | select(.id=="4fb05d17267d")' ~/.hermes/cron/jobs.json
# → has next_run_at, last_run_at, repeat.completed, last_status, origin, workdir

# Broken job — bare-minimum schema
jq '.jobs[] | select(.id=="self-improve-hourly")' ~/.hermes/cron/jobs.json
# → MISSING next_run_at, last_run_at, repeat, last_status, origin
# (typical when registered via direct jq write, bypassing add_job())
```

The bare-minimum schema is the signature of a registration that bypassed `add_job()` (and therefore bypassed the recovery / normalization layer). Such jobs depend on the recovery branch to populate `next_run_at` on first tick — and the recovery branch is exactly where the iterator crashes on other malformed entries.

**Detection protocol (use BEFORE assuming "scheduler is broken" or "cron is silently disabled"):**

```bash
# 1. Confirm the scheduler is alive (often inside the gateway, not a standalone daemon)
ps -ef | grep -E "hermes gateway|scheduler" | grep -v grep

# 2. Find which runtime python the tick loop actually uses
#    (Often a venv; using system python3 will mis-diagnose as "croniter missing")
grep -E "cron.scheduler.tick|cron_tick" ~/.hermes/hermes-agent/gateway/run.py | head -3

# 3. Invoke get_due_jobs() directly with the runtime's python
<runtime-venv>/bin/python -c \
  "from cron.jobs import get_due_jobs; print(get_due_jobs())"

# 4. If you see AttributeError / TypeError → one malformed entry is poisoning the loop.
#    Find it: jobs without next_run_at, sorted by registration order. The crash
#    aborts iteration BEFORE your broken job.
jq '.jobs | map(select(.next_run_at == null)) | map({id, schedule_type: (.schedule | type)})' \
  ~/.hermes/cron/jobs.json
```

**Match in production (2026-08-04):** `self-improve-hourly` registered 2026-08-03 with bare-minimum schema. Two earlier-registered jobs (`otto-daily-digest`, `otto-db-cleanup`) had `schedule` as bare strings. The dispatch loop hit one of them first, crashed, and `self-improve-hourly` never got its `next_run_at` populated. Other jobs that already had `next_run_at` skipped the recovery branch (`if not next_run:`), so they kept working — masking the defect.

**Rule:** when the briefing finds a `last_run_at: null` job in `hermes cron list`, do NOT conclude "scheduler is broken" or "this job is silently disabled." Invoke the due-job iterator directly with the runtime's actual python (not system python3) and read the error. If a malformed entry is poisoning the loop, the iterator output will say so — that's the briefing's unique value-add, since the cron `last_status` field reports nothing useful when the tick driver swallows the exception at DEBUG level.

**Sub-rule for the briefing's "Cron health" section:** report `last_run_at: null` jobs with the bare-minimum-schema tell ("registered without going through add_job()") and the iterator-crash detection protocol as the diagnostic next step. The fix is two-part: defensive normalization in the iterator + schema validation at registration. See `systematic-debugging` Phase 1, item 7 for the full recipe.

### 14. Auto-fix budget during an audit: 3 fixes per audit is the upper limit (added 2026-07-02)

**Observation:** When a recurring briefing / strategist-audit / project-health-audit identifies multiple recurring recommendations across multiple prior audit cycles, the temptation is to fix everything in one audit. This leads to (a) the audit taking longer than the cron budget, (b) half-applied patches that break unrelated behavior, and (c) audit-report deliverable arriving after the cron timeout.

**Rule:** an audit auto-fixes up to **3 simple structural fixes** per cycle. Anything more complex (multi-file changes, design questions, dependency choices) gets dispatched to Claude Code as a background task with full context. The audit's P0/P1/P2 recommendations remain in the report regardless of auto-fix scope.

**Sizing the fixes:**
- **Tier 1 (auto-fix in audit):** 1-line classifier changes, path corrections in JSON files, `latest.json` pointer writes, dedup cursor logic. ≤30 lines, deterministic, easily reversible.
- **Tier 2 (dispatch to Claude):** Python script rewrites, dependency changes, config-schema changes, anything touching the runtime.
- **Tier 3 (escalate to user):** billing/auth changes, model swaps, anything `needs_human`.

**Audit-time budget:** The audit itself runs as a cron with a typical 600s budget. Reading + analysis ≈ 30%. Auto-fixes ≈ 30%. Report writing ≈ 30%. Reserve 10% for post-claim verification. Going over the budget will time out the cron and lose the deliverable.

### 17. Per-project POPDD chain receipts at `~/.lux/test-receipts/chain-<ts>.jsonl` (added 2026-08-06)

**Symptom (matched 2026-08-06 daily-activity cron):** The PDD activity ledger reads `~/.lux/proving-ground/<date>.jsonl` and `~/.lux/receipts/<date>.jsonl` to assemble "functions modified / specs verified / regressions blocked / new specs." Both came back close to empty today (`proving-ground` showed 8 PASS but no `target` function names; `receipts/<date>.jsonl` was 1-line `INITIALIZED`). Yet the `lux` project itself had a 4-entry chained, HMAC-signed log at `~/Documents/code/lux/.lux/test-receipts/chain-2026-08-06T16-27-15-062Z.jsonl` — the richest single record of what was modified, what was verified (with `passedClauses / totalClauses / invariantSamples`), and what was tested (with `tests / passed / failed / duration_ms`).

**Why this source isn't in Step 5b's table:** when `popdd-on-lux` is integrated into a project, that project's POPDD chain writes to a project-local path (`<project>/.lux/test-receipts/chain-<timestamp>.jsonl`), NOT to the cross-project `~/.lux/receipts/<date>.jsonl`. The latter is only populated by the hermes-agent receiver (`popdd-inline-attestation` merges hermes-session actions into it; the 1-line `INITIALIZED` we saw is exactly that — the hermes session boot, not project work).

**The full data source set (corrected):**

| Axis | Primary disk source | Additional chain-receipt cross-check |
|---|---|---|
| Functions modified | `~/.lux/proving-ground/<date>.jsonl` (verify entries name targets) | `<project>/.lux/test-receipts/chain-<ts>.jsonl` — `action: "edit"` entries include `added`/`diffLines` for the exact edit |
| Specs verified | `~/.lux/receipts/<date>.jsonl` (`action: "verify"`) | `<project>/.lux/test-receipts/chain-<ts>.jsonl` — `action: "verify"` with `proof.passedClauses`, `proof.totalClauses`, `proof.invariantSamples` |
| Regressions blocked | `~/.lux/receipts/<date>.jsonl` filter `verdict: "FAIL"` | Same chain file — `verdict: "FAIL"` entries |
| New specs created | `~/.lux/specs/*.json` mtime >= today | Same chain file — `action: "edit"` entries with `added: ["WEIGHTED_AVERAGE_SPEC"]` etc. |

**Discovery recipe:**

```bash
# Find any project-local chain receipts written today
find ~/Documents/code -path '*/.lux/test-receipts/chain-*.jsonl' \
  -newermt "$(date +%Y-%m-%d)" 2>/dev/null
# Or scoped to ~/.lux if the cron sandbox blocks ~/Documents/code
find ~/.lux/test-receipts -name 'chain-*.jsonl' \
  -newermt "$(date +%Y-%m-%d)" 2>/dev/null
```

**Rule:** when the PDD ledger report feels thin but `~/Documents/code/*/.lux/test-receipts/` is unreadable from the cron sandbox (Pitfall #14 territory), still list `~/.lux/test-receipts/` as the **last-resort fallback** for the chain-receipt layer. If that's empty too, the activity genuinely didn't happen at the project layer — `popdd-on-lux` is integrated per-project, so its absence on a given day is real data.

**Honest-gaps footer amendment:** add a line acknowledging whether chain receipts were surveyed per-project, e.g. "Per-project POPDD chains surveyed at `<N>` project `.lux/test-receipts/` directories (sandbox-blocked projects counted in gaps)."

### 18. Proving-ground `state` field is pretty-printed JSON with spaces — `grep` with no whitespace gets 0 hits (added 2026-08-06)

**Symptom (matched 2026-08-06 daily-activity cron):** `grep -c '"state":"pass"' ~/.lux/proving-ground/2026-08-06.jsonl` returns **0**. Yet opening the file in `read_file` shows 8 `state: "pass"` entries. The naive count is wrong, not the file.

**Why it bites:** `~/.lux/proving-ground/*.jsonl` entries are written by the auditor's `json.dumps(...)` without `separators=(",", ":")`, so the output looks like:
```json
{"project": "lux-spec", "check": "tests", "state": "pass", ...}
```
with **spaces after colons**. A grep for `"state":"pass"` (no space) misses all of them. The companion receipt files at `~/.lux/receipts/*.jsonl` are written by `json.dumps(...)` directly too, but the keys are different (`verdict`, `action`) so the gotcha typically hits the `state` field most.

**Rule:** when counting pass/fail/skip from `~/.lux/proving-ground/*.jsonl` with grep, **always include the space**:
```bash
grep -c '"state": "pass"'    ~/.lux/proving-ground/$(date +%Y-%m-%d).jsonl
grep -c '"state": "failed"'  ~/.lux/proving-ground/$(date +%Y-%m-%d).jsonl
grep -c '"state": "skipped"' ~/.lux/proving-ground/$(date +%Y-%m-%d).jsonl
```
For receipt files, use the jq recipes in `references/pdd-activity-ledger.md` — they sidestep the whitespace entirely.

## Companion Files
**Rule:** an audit auto-fixes up to **3 simple structural fixes** per cycle. Anything more complex (multi-file changes, design questions, dependency choices) gets dispatched to Claude Code as a background task with full context. The audit's P0/P1/P2 recommendations remain in the report regardless of auto-fix scope.

**Sizing the fixes:**
- **Tier 1 (auto-fix in audit):** 1-line classifier changes, path corrections in JSON files, `latest.json` pointer writes, dedup cursor logic. ≤30 lines, deterministic, easily reversible.
- **Tier 2 (dispatch to Claude):** Python script rewrites, dependency changes, config-schema changes, anything touching the runtime.
- **Tier 3 (escalate to user):** billing/auth changes, model swaps, anything `needs_human`.

**Audit-time budget:** The audit itself runs as a cron with a typical 600s budget. Reading + analysis ≈ 30%. Auto-fixes ≈ 30%. Report writing ≈ 30%. Reserve 10% for post-claim verification. Going over the budget will time out the cron and lose the deliverable.

## Companion Files

- `references/briefing-data-sources.md` — file paths, formats, and freshness semantics for every artifact the briefing reads
- `references/sample-morning-briefing.md` — a worked example showing the exact output format with real file excerpts
- `references/cron-state-reconciliation.md` — the full cross-reference table of `last_status` vs disk truth, with worked examples for each common cron
- `references/timezone-and-date-arithmetic.md` — handling "yesterday" across UTC/local, macOS vs Linux date syntax, and the multi-day gap case
- `references/llm-provider-failure-modes.md` — the full catalog of LLM-provider failure modes that masquerade as cron timeouts (402 billing, 429 rate-limit, 401 auth, network stalls, model-not-found). Includes the detection protocol and watchdog classifier pattern.
- `references/pdd-activity-ledger.md` — disk-artifact data sources for the four PDD axes (functions modified, specs verified, regressions blocked, new specs created). Includes the sandbox-blocked fallback recipe and a worked example.
