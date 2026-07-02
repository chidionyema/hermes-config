---
name: recurring-briefing
description: Recurring scheduled narrative briefings — morning briefings, end-of-day reports, weekly rollups, post-incident summaries. Aggregates disk artifacts (health JSONL, watchdog alerts, gap-finding reports, daily reflections, OBJECTIVES, cron state) into a single structured human-readable report. Read-only by design — runs no tests, dispatches no agents, performs no mutations. Load when the user asks for "morning briefing", "what's the state of things", "give me the daily", "end of day report", or when a cron job is scheduled to deliver a periodic status report.
version: 1.0.0
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

### 13. Auto-fix budget during an audit: 3 fixes per audit is the upper limit (added 2026-07-02)

**Observation:** When a recurring briefing / strategist-audit / project-health-audit identifies multiple recurring recommendations across multiple prior audit cycles, the temptation is to fix everything in one audit. This leads to (a) the audit taking longer than the cron budget, (b) half-applied patches that break unrelated behavior, and (c) audit-report deliverable arriving after the cron timeout.

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
