# Sample Morning Briefing — Worked Example

A complete worked example showing the exact output format a recurring morning briefing should produce. This is the 2026-07-02 morning briefing from Otto's estate, presented as it was actually delivered.

The example includes real (anonymized) findings that triggered the pitfalls documented in the parent SKILL.md. Read it to see what "good" looks like in the wild.

---

**Morning Briefing — 2026-07-02**

**Yesterday:**
- No self-reflection file written yesterday (or for 8 days — last was 2026-06-24). The 6pm `daily-self-reflection` cron has been silent. The file `~/.hermes/logs/reflection/2026-06-24.md` listed 6 unfixed escalated tasks (signalengine/prospector timeouts, one "Hello Otto, are you there?" acceptance test) plus 3 stale processes. None of those carry-over items are documented as resolved.
- Idle-learning pipeline ran all night — 5 clean `Complete` runs between 04:44 and 06:45 UTC, no failed phases.
- Meta-improver retired 5 zero-hit policies (pol-20260618-003/006/010/012 + pol-auto-engineering-reliability-20260618) at 2026-07-01T20:55:30Z. All 5 were evaluated as `improved` or `neutral` by 03:14Z today. Outcome velocity is back to 0.0 — pipeline is steady.
- Gap-finding (07:45) is identical to yesterday's (07:01): same 3 uncovered domains (testing 179 hits, task-management 179 hits, api_usage 1 hit) and same 3 weak-coverage domains. 7 days of "no change" is a signal that gap-finding is producing reports but not feeding actions.
- A 7:00am strategist audit started but never produced output — `task-state/current_task.json` shows `interrupted: true`, `tool_calls_completed: 0`. The cron fired at 07:00 and aborted before reading a single file. **No strategist audit report exists for today.**

**Self-Improvement Health:**
- Domain coverage: 50.0% (unchanged from 06-15, flat for 17 days)
- Untriggered policies: 3 — pol-20260618-004 (1 hit), pol-20260618-008 (1 hit), pol-auto-engineering-reliability-20260701 (0 hits, 1 day old)
- Uncovered domains: 3 (testing / task-management / api_usage)
- Outcome velocity: 0.0 — pipeline flat
- Active policies: 5, all healthy
- Reflect-on-correction: still produces duplicate blocks when it runs (the 06-23 audit's #1 issue, prescribed in 06-20/21/22 audits, never patched)
- POPDD chain: no receipts since 2026-06-19 (13-day gap; F1 retrieval still tag-only-fallback)

**Project Health** (last repo-health.jsonl, 2026-07-02T06:38:05Z, verbatim):
```
{"signalengine": {"state": "dirty", "summary": "signalengine: DIRTY (2 uncommitted)"},
 "lux":        {"state": "dirty", "summary": "lux: DIRTY (2 uncommitted)"},
 "prospector": {"state": "dirty", "summary": "prospector: DIRTY (2 uncommitted)"}}
```
- Signal: **dirty** (2 uncommitted)
- LUX: **dirty** (2 uncommitted)
- Prospector: **dirty** (2 uncommitted) — all three repos have been "DIRTY (2 uncommitted)" for 6+ consecutive 2h health checks. Same 2 uncommitted files in each repo, not growing — almost certainly `__pycache__` / untracked runtime files, not real work-in-progress.

**Cron health (active issues):**
- 🔴 `health-watchdog` — exited 1 at 08:54 today: `UnboundLocalError: cannot access local variable 'datetime' where it is not associated with a value` in `watchdog-cron.py`. **Fresh error, recurring every 15m until fixed.**
- 🔴 `morning-briefing` — last errored 2026-06-23 (TimeoutError 936s). Has not run successfully since, but the 9am delivery slot keeps timing out. **This very briefing is the job that errored — proof the cron job itself is structurally broken.**
- 🟡 `daily-self-reflection` — last successful run 2026-06-24. 8 days of missing reflections.
- 🟡 `daily-strategist-audit` — today's 7am invocation interrupted before any work. The cron fires but doesn't complete.
- 16 other cron jobs: all `ok` at last run.

**Watchdog alerts:** 1 open fingerprint (the morning-briefing timeout from 06-23), still firing every 15m.

**Carry-over from yesterday (and prior days):**
1. **health-watchdog is currently broken** — UnboundLocalError on `datetime`. The watchdog that is supposed to detect breakage is itself broken.
2. **morning-briefing cron has been broken for 9 days** (06-23 → today). This briefing is being delivered despite the cron — the system isn't depending on the cron path.
3. **Strategist audit cron: interrupted at 07:00 today** — needs a retry or root-cause investigation.
4. **reflect-on-correction.py spam** — prescribed in 06-20, 06-21, 06-22, 06-23 audits. Never patched.
5. **6 unstick items from 2026-06-24 reflection** — all still open or stale.
6. **Gap-finding producing the same report 7 days running** — uncovered domains haven't shifted; the meta-loop is not closing.
7. **POPDD receipts have a 13-day gap** — methodology probe is silent (dedup is hiding active issues).
8. **Daily self-reflection hasn't run in 8 days** — the `daily_reflection.py` path fix from 06-23 audit may have regressed.

**What are today's priorities?**
1. **Fix health-watchdog UnboundLocalError first** — the watchdog is the system that detects everything else. If it's down, the whole monitoring story is silent.
2. **Investigate the 7:00am strategist-audit interruption** — was it a session timeout, an LLM provider issue, or a script bug? The `interrupted: true, tool_calls_completed: 0` state is suspicious.
3. **Fix the morning-briefing cron** (or accept it's structurally dead and move the briefing to a different delivery path).
4. **Apply the gap-finding acceleration interventions** — tag corpus entries, wire the methodology-probe hook, force one cycle that closes at least one of the 3 uncovered domains.
5. **Decide on the 6 unstick items from 06-24** — if they're still real, dispatch them; if they've been resolved, close them.

---

## What This Briefing Did Right

1. **Verbatim health JSONL.** The `repo-health.jsonl` line is pasted as-is, not paraphrased. The reader can verify against the file.
2. **Cross-referenced cron state with disk artifacts.** The "active issues" section distinguishes:
   - `health-watchdog` — disk says it's erroring (current stderr in the cron list)
   - `morning-briefing` — disk says it timed out 9 days ago, and that error persists
   - `daily-self-reflection` — disk says no reflection file since 06-24
   - `daily-strategist-audit` — disk says the report is missing for today, AND `task-state/current_task.json` shows `interrupted: true`
3. **Surfaced the briefing's own broken delivery path.** The `morning-briefing` cron entry is explicit: "This very briefing is the job that errored." This is not a contradiction; it's the briefing's job to surface that future auto-deliveries will fail.
4. **Priorities are 1-3-5, not 1-10.** The 8 carry-over items in the previous section collapse to 5 priorities. Anything more would be a triage failure.
5. **Each finding cites the file path or the source.** `~/.hermes/meta/change-outcomes.jsonl`, `~/.hermes/logs/reflection/2026-06-24.md`, `task-state/current_task.json`, the cron stderr.

## What This Briefing Did Not Do

- **Did not run tests.** No `pytest`, no `npm test`. The repo health JSONL is the source of truth.
- **Did not call `git status --short`.** The health JSONL already has the uncommitted count. Re-running git status would be redundant.
- **Did not fix any of the findings.** The briefing is a deliverable, not a fix. The 5 priorities are recommendations; execution is a separate event.
- **Did not add "let me know if you want me to act."** The user will say so if they want it.
- **Did not interpret "DIRTY (2 uncommitted)" as a crisis.** Steady-state dirt in 3 repos across 6+ checks is noted ONCE in the project health section, not re-flagged as a fresh finding in priorities.
- **Did not ask "should I fix the morning-briefing cron now?"** The cron is broken; the briefing says so; the user decides.

## What This Briefing Did Wrong

A real critique of this output:

1. **The "8 days of missing reflections" claim needs a citation.** The reflection directory listing shows files for 06-23 and 06-24 only. The 8-day claim is from `ls -la ~/.hermes/logs/reflection/` — the briefing should have said "last reflection: 2026-06-24 (`ls -la ~/.hermes/logs/reflection/` shows only 2026-06-23.md and 2026-06-24.md)."
2. **The "flat for 17 days" claim is dramatic but unsupported.** The briefing has no historical domain_coverage_pct data showing 50.0% on 06-15. This number was inferred from the auditor's memory, not retrieved from disk. **The fix:** if the briefing can't cite a specific data point showing 50.0% on 06-15, drop the "flat for 17 days" claim and report "domain_coverage_pct: 50.0% (today's reading) — trend unknown."
3. **"Same 2 uncommitted files in each repo, not growing" was inferred, not verified.** The 6+ checks were cited, but the briefing did not actually diff the uncommitted file lists across the 6 checks. If the dirt is different files in different checks, the briefing is wrong.
4. **The "carry-over from prior days" section is a laundry list.** 8 items is too many. The briefing should triage: items 1-2-3 are the actively-broken-now findings, items 4-5-6-7-8 are the long-running-but-not-emergencies. Lumping them as one section flattens the priority.

These are real critiques. The next iteration of the briefing should:
- Cite file paths for every claim (reflexively, not just when convenient)
- Distinguish "today's reading" from "trend" explicitly
- Triage the carry-over section into "broken now" vs "stale but not blocking"

## Patterns to Reuse

**Pattern: "Last run X, expected Y, found Z"**
```
The 6pm daily-self-reflection cron has been silent for 8 days.
Last reflection: 2026-06-24 (ls -la ~/.hermes/logs/reflection/ shows only 2026-06-23.md and 2026-06-24.md).
Expected: a new file each day. Found: nothing since 2026-06-24.
```

**Pattern: "Cron self-report contradicts disk state"**
```
hermes cron list | grep "daily-self-reflection" → Last run: 2026-06-24T18:00:58  ok
ls -t ~/.hermes/logs/reflection/ | head -1 → 2026-06-24.md (8 days stale)
The cron is reporting success on its last run but has not produced output for 8 days.
```

**Pattern: "Pipeline flat for N days"**
```
Domain coverage: 50.0% (unchanged from prior postflight events).
Gap-finding report: 3 uncovered domains, identical to 2026-07-01, 2026-06-30, 2026-06-29.
The meta-improvement loop is not finding new signal — not because the pipeline is broken, but because the corpus is not receiving new input.
```

**Pattern: "This briefing is the job that errored"**
```
The 9am morning-briefing cron has been erroring for 9 consecutive days
with TimeoutError 936s (limit 600s). The briefing you are reading
was delivered through an alternate path; future auto-deliveries will
also fail until the cron is fixed.
```

These four patterns cover ~80% of recurring briefing findings. Build them into the briefing template and the format will be consistent across sessions.
