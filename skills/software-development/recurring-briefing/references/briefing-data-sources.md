# Briefing Data Sources

Every artifact a recurring briefing reads, with the exact path, the format on disk, the freshness semantics, and the gotcha that bit during real briefings.

## 1. Project Health Snapshot

**Path:** `~/.hermes/logs/health/repo-health.jsonl`
**Format:** JSONL — one entry per 2h health probe cycle
**Producer:** `repo-health-check.py` cron (every 2h)
**Read command:** `tail -1 ~/.hermes/logs/health/repo-health.jsonl`

**Schema:**
```json
{
  "timestamp": "2026-07-02T06:38:05Z",
  "results": {
    "signalengine": {"state": "dirty", "summary": "signalengine: DIRTY (2 uncommitted)"},
    "lux":         {"state": "dirty", "summary": "lux: DIRTY (2 uncommitted)"},
    "prospector":  {"state": "dirty", "summary": "prospector: DIRTY (2 uncommitted)"}
  }
}
```

**States:** `pass` | `dirty` | `fail` | `skip`

**Briefing use:** paste the entry verbatim. The `summary` field already includes the count. Do NOT run `git status --short` to "verify" — the snapshot is the source of truth.

**Gotcha:** the repo paths the probe checks are `~/code/<name>` or `~/Documents/code/<name>` depending on configuration. The probe is hard-coded; if the briefing runs `git -C ~/projects/signalengine status --short` it gets a different (possibly empty) result. **Always read the JSONL; never probe the repos directly in a briefing.**

**Steady-state detection:** if the last 3 entries have identical `summary` fields, the dirt is steady-state (e.g. `__pycache__`, runtime files, untracked ignored files). Report as "steady-state" not as a fresh finding. Use `git -C <repo> status --short` to confirm the dirt is not growing — but ONLY if you suspect growth, not for every briefing.

## 2. Gap-Finding Report

**Path:** `~/.hermes/logs/maintenance/gap-finding-YYYY-MM-DD.md`
**Format:** Markdown with 🔴/🟡/🟢 sections
**Producer:** `gap-finding.py --report` (in idle-learning pipeline, every 30m)
**Read command:** `ls -t ~/.hermes/logs/maintenance/gap-finding-*.md | head -1`

**Briefing use:** read the latest report. Look for:
- Uncovered domains (🔴) — corpus mentions the domain with no policy/skill coverage
- Weak coverage (🟡) — domain has a policy but the failures continue
- Coverage trend (compare to yesterday's report if you want to detect progress)

**Gotcha:** the report is **byte-identical across days** if the underlying corpus hasn't changed. This is the "pipeline starved for signal" signal, not a fresh finding. Compare with `diff <(cat <latest>) <(cat <yesterday>)` — if zero diff, the meta-loop is flat.

**Anti-pattern:** reporting "3 uncovered domains" every briefing as if it's a new finding. The first day is news; the fifth day is "pipeline is stalled."

## 3. Near-Miss Analysis

**Path:** `~/.hermes/logs/maintenance/near-miss-YYYYMMDD-HHMMSS.json`
**Format:** JSON with `untriggered_policies`, `co_firing_contexts`, `domain_coverage_gaps`
**Producer:** `near-miss-analyzer.py` (every 30m)
**Read command:** `ls -t ~/.hermes/logs/maintenance/near-miss-*.json | head -1`

**Briefing use:** the `untriggered_policies` list shows policies with 0 hits that are candidates for demotion. The `domain_coverage_gaps` shows corpus entries with no policy.

**Gotcha:** the analyzer produces a new file every 30m with structurally identical content. This is the "113 near-miss files all structurally identical" pitfall from the 2026-06-21 audit. The briefing should:
- Note untriggered policies by ID, not by file count
- Skip the "produced N files today" framing

**Structural fix (out of scope for the briefing):** the analyzer should be patched to write JSONL or hash-before-write. The briefing is read-only and does not make that change.

## 4. Daily Self-Reflection

**Path:** `~/.hermes/logs/reflection/YYYY-MM-DD.md`
**Format:** Markdown following the audit template (failures / mistakes / corrections / stale processes / waited / improvement plan)
**Producer:** `daily_reflection.py` cron (6pm daily)
**Read command:**
```bash
# Yesterday's reflection (macOS)
ls ~/.hermes/logs/reflection/$(date -v-1d +%Y-%m-%d).md 2>/dev/null
# Yesterday's reflection (Linux)
ls ~/.hermes/logs/reflection/$(date -d yesterday +%Y-%m-%d).md 2>/dev/null
# Most recent reflection (fallback)
ls -t ~/.hermes/logs/reflection/ | head -1
```

**Briefing use:** the "Improvement Plan for Tomorrow" section auto-fills from the latest gap-finding report. The briefing reports which items from yesterday's plan are still open.

**Gotcha — the file may be empty or missing for >24h.** If `daily_reflection.py` is broken (path issue, script error), the file is missing entirely. Check the cron `last_status` for `daily-self-reflection`:
- `last_status: ok` AND file exists with content → reflection ran
- `last_status: ok` AND file does NOT exist → cron is reporting success but not producing output (the classic `last_status: ok` lie)
- `last_status: error` → cron is failing

**Gotcha — the file exists but is full of duplicate "Auto-Reflection" blocks.** This is the `reflect-on-correction.py` spam bug (prescribed in 2026-06-20/21/22/23 audits, never patched). The `grep -c "Auto-Reflection"` count tells you: ≤1 is healthy, >1 is the bug.

## 5. Meta-Improver Outcomes

**Path:** `~/.hermes/meta/change-outcomes.jsonl`
**Format:** JSONL with `change_id`, `change_type`, `description`, `applied_at`, `outcome`, `outcome_determined_at`
**Producer:** `outcome-accelerator.py` (auto-fires on `mark_task_complete()`)
**Read command:** `tail -3 ~/.hermes/meta/change-outcomes.jsonl`

**Briefing use:** the most recent outcomes — were changes `improved`, `neutral`, or `regressed`? This is the empirical signal of whether the self-improvement loop is working.

**Gotcha:** outcomes have a delay. A change applied at 20:55 may not have `outcome_determined_at` until 03:14 the next day. The briefing should not conclude "no recent changes worked" if the most recent change is <6h old.

## 6. Improvement Velocity

**Path:** `~/.hermes/meta/metrics.jsonl`
**Format:** JSONL with `event: postflight`, `policy_count`, `active_count`, `coverage_pct`, `domain_coverage_pct`, `improvement_velocity`
**Producer:** `meta-improver.py --postflight` (Phase 8 of idle-learning, every 30m)
**Read command:** `tail -3 ~/.hermes/meta/metrics.jsonl`

**Briefing use:** `improvement_velocity` (a number, 0.0 = no movement) and `domain_coverage_pct` (percentage of corpus domains with policies). These are the two velocity signals.

**Dual-velocity rule:** `coverage_pct` measures regression coverage (corpus entries that have a matching policy) and is misleadingly low early on. `domain_coverage_pct` measures the percentage of corpus *domains* with policies. **Use `domain_coverage_pct` as the primary signal in the first week**, then graduate to `coverage_pct` once the corpus exceeds 30 entries.

**Steady-state detection:** if `domain_coverage_pct` is identical for 7+ consecutive postflight events, the meta-improver is not finding new domains to cover. Report as "velocity flat for N days" once, not as a fresh finding every briefing.

## 7. Cron State

**Path:** `hermes cron list` (CLI output, not a file)
**Format:** text table with `Name`, `Schedule`, `Last run`, `Last run: <timestamp> ok|error`
**Producer:** live query of `~/.hermes/cron/jobs.json` (per profile)
**Read command:**
```bash
# All errored crons with context
hermes cron list | grep -B2 "error:"
# All crons with last-run state
hermes cron list | grep -E "(Name|Last run)"
```

**Briefing use:** list every cron with `error:` in its last run, with the error type and last attempt timestamp. The briefing's main value is distinguishing:
- Real failures (script bug, missing file) → report
- Designed exits (`reason=preempted`, intentional `exit 1` for alerting) → silent or note

**Gotcha — `last_status: ok` does not mean the job worked.** This is the #1 briefing pitfall. The cron stores its own self-reported status; the actual output is in the `stderr` field. The briefing must check BOTH the cron list AND the disk artifacts the cron should have produced. The cross-reference table is in `references/cron-state-reconciliation.md`.

**Gotcha — the `Script:` field can be wrong.** If the cron was edited with an inline `#!` shebang, the script field literally contains `#!/bin/bash` as a "path" → "Script not found" errors every run. Detection: `hermes cron list | grep -E "Script:.*#\!"`. This is a real production bug, not theoretical.

## 8. Watchdog Alerts

**Path:** `~/.hermes/logs/alerts/watchdog.jsonl`
**Format:** JSONL with `type` (e.g. `CRON_ERROR`, `GIT_DIRTY`, `watchdog_summary`), `message`, `healthy`, `status` (`open` | `resolved`)
**Producer:** `watchdog.py` (every 15m)
**Read command:** `tail -10 ~/.hermes/logs/alerts/watchdog.jsonl`

**Briefing use:** open fingerprints (the same alert firing on consecutive runs is a single fingerprint; a fingerprint is "open" if the latest entry has `status: open`). The briefing should report:
- Count of open fingerprints
- The most recent 1-2 alert messages verbatim
- Cross-reference with `last_status` for the affected cron

**Gotcha — the watchdog can re-fire on its own errors.** If the watchdog itself is broken (e.g. `UnboundLocalError`), it exits 1 → "watchdog errored" alert → watchdog re-runs → re-errors → re-alerts. The result is hundreds of `watchdog_summary` entries in a day. The briefing should:
- Count unique fingerprints, not total entries
- Note "watchdog's own errors are inflating the count" if `watchdog_summary` is the dominant entry type

**Gotcha — type field can be `UNKNOWN` or `?`.** If the optimization report shows `Alert type '?' fired N times`, the watchdog is writing lumped `{"alerts": ["..."]}` format instead of typed individual entries. This is a bug, not a finding the briefing should paper over.

## 9. Active Objectives

**Path:** `~/.hermes/OBJECTIVES.md`
**Format:** Markdown table with `ID | Objective | Success Criteria | Status | Started`
**Producer:** manual edits by the agent or user
**Read command:** `cat ~/.hermes/OBJECTIVES.md`

**Briefing use:** report the count of active objectives. If zero, the briefing notes "no active objectives on the stack" — the agent has no current focus.

**Gotcha:** the file has a "Pattern for success criteria" section at the bottom that is documentation, not objectives. Don't count it as active work.

## 10. Interrupted Tasks

**Path:** `~/.hermes/task-state/current_task.json`
**Format:** JSON with `task`, `started_at`, `interrupted: bool`, `tool_calls_completed`, `last_action`
**Producer:** `task_state.py save` (called before every tool call)
**Read command:** `cat ~/.hermes/task-state/current_task.json`

**Briefing use:** if `interrupted: true`, surface the task description and the `tool_calls_completed` count. P0 finding.

**Gotcha:** the `interrupted: true` state may be from a session that ended normally but didn't run `task_state.py clear`. The `last_action: "manual save"` field tells you whether the save was a defensive save (interrupted) or a deliberate checkpoint (still in progress). If `last_action: "manual save"` AND the timestamp is recent AND no in-flight work, the file is stale and can be ignored.

## 11. Estate Optimization Report

**Path:** `~/.hermes/reports/estate-optimization.md`
**Format:** Markdown with priority sections + "Actions Required" checklist
**Producer:** `estate-optimization-scanner.py` (part of `estate-full-run.sh`, 6am daily)
**Read command:** `cat ~/.hermes/reports/estate-optimization.md 2>/dev/null`

**Briefing use:** the highest-priority items in the report become the briefing's "priorities" section.

**Gotcha:** the report's `actions_required` section has unchecked boxes (`[ ]` vs `[x]`) representing recommendations. If the unchecked items have been unchecked for 3+ days, the briefing should note "carry-over items not addressed" and may want to call out that estate-management's auto-remediation phase is dry-run only.

## 12. Project Status Reports (Deep Dives)

**Path:** `~/.hermes/reports/project-status-<project>.md`
**Format:** Markdown with provenance, scale, key components
**Producer:** on-demand (not cron-driven)
**Read command:** `ls -t ~/.hermes/reports/project-status-*.md`

**Briefing use:** these are deep dives, NOT briefings. The briefing should reference them in the "Project Health" section ("see `project-status-signalengine.md` for full graph metrics") but should NOT paste their content.

**Gotcha:** these files are stale by design. A 2026-06-22 status report is "stale" relative to a 2026-07-02 briefing. The briefing should note "stale since <date>" if the file is >7 days old.

## File Path Map (Quick Reference)

| What | Path | Cadence |
|------|------|---------|
| Repo health | `~/.hermes/logs/health/repo-health.jsonl` | 2h |
| Gap-finding | `~/.hermes/logs/maintenance/gap-finding-*.md` | 30m |
| Near-miss | `~/.hermes/logs/maintenance/near-miss-*.json` | 30m |
| Reflection | `~/.hermes/logs/reflection/YYYY-MM-DD.md` | 24h (6pm) |
| Outcomes | `~/.hermes/meta/change-outcomes.jsonl` | per change |
| Metrics | `~/.hermes/meta/metrics.jsonl` | 30m |
| Cron state | `hermes cron list` (live) | live |
| Watchdog alerts | `~/.hermes/logs/alerts/watchdog.jsonl` | 15m |
| Objectives | `~/.hermes/OBJECTIVES.md` | manual |
| Task state | `~/.hermes/task-state/current_task.json` | per tool call |
| Estate optimization | `~/.hermes/reports/estate-optimization.md` | 24h (6am) |
| Project status | `~/.hermes/reports/project-status-*.md` | on-demand |
