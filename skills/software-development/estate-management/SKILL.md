---
name: estate-management
description: "Estate lifecycle: inventory, drift detection, optimization scanning, auto-remediation, and daily audit cadence for complex Hermes configurations. Covers the full pipeline from cataloging components to executing improvements."
version: 1.1.0
author: LUX Engine
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [estate, inventory, audit, drift-detection, optimization, remediation, cron, monitoring]
    related_skills: [otto-operating-model, project-health-audit, hermes-self-audit]
prerequisites:
  files:
    - ~/.hermes/scripts/estate-inventory.py
    - ~/.hermes/scripts/estate-drift-detector.py
    - ~/.hermes/scripts/estate-optimization-scanner.py
    - ~/.hermes/scripts/estate-auto-remediation.py
    - ~/.hermes/scripts/estate-full-run.sh
---

# Estate Management

When a user asks "what is my stack" or "audit everything" or "do we have an estate inventory" — or when the configuration has grown complex enough that no single person (including the agent) can describe all components — this skill provides the full estate lifecycle.

## Core Principle

**Inventory is not review. Review is not improvement.** Three distinct phases, run in order:

1. **Inventory** — catalog every component (scripts, skills, policies, cron, repos, logs, models)
2. **Review** — compare to baseline (drift) + analyze pipeline outputs (optimization)
3. **Improvement** — execute or preview remediation (archive dead policies, consolidate overlap)

Each phase depends on the previous. Never run improvement without first understanding what changed.

## Phase 1: Estate Inventory

Script: `estate-inventory.py`

Catalogs:
- Hermes version + config size
- All scripts in `~/.hermes/scripts/` (.py, .sh)
- All skills (grouped by category)
- All policies with hit counts and statuses
- All cron jobs with schedules and last-run status
- Log directories with file counts
- ML model location and size
- External repos tracked (git SHAs)

Output: `~/.hermes/reports/estate-inventory.md`

**When to run:** Daily via cron. Also run on-demand when user asks "what's in my stack."

**Pitfall:** The inventory script (`scripts/estate-inventory.py`) outputs a raw report to stdout. For Telegram delivery, use `estate-full-run.sh` which wraps it with drift + optimization + remediation.

## Phase 2: Drift Detection

Script: `estate-drift-detector.py`

Takes a JSON snapshot of the current estate state and compares it to the most recent snapshot. Produces a report **only when something changed**.

What it flags:
- New/removed scripts — each named individually
- New/removed skills — by name
- **Skill bloat** — if skills grew by >5 since last snapshot
- New/removed cron jobs — including auto-detected stale (never-ran) jobs
- New/removed policies — by ID and domain
- **Policy inactivity** — zero-hit policies, stalled policies (hits not incrementing)
- **Config changes** — MD5 hash diff on config.yaml

Output: `~/.hermes/reports/estate-drift.md` (only produced when drift exists)

**Key design decision:** Silent if no drift. The report file is deleted on no-drift runs so cron deliverers don't push empty updates.

**Snapshot storage:** `~/.hermes/reports/snapshots/estate-YYYYMMDD-HHMMSS.json`

**Pitfall:** First run always produces "First snapshot — baseline established" which is an info message, not drift. The script correctly categorizes this.
**Pitfall:** The drift detector's action items section may reference variables (`skill_growth`) that are out of scope in `generate_report()`. Test after editing the action-items section.

## Phase 3: Optimization Scanner

Script: `estate-optimization-scanner.py`

Reads ALL existing pipeline outputs and synthesizes them into ranked recommendations:

Sources consumed:
- Meta-improver bottleneck reports (last 5)
- Near-miss analysis (latest)
- Trend analysis (latest)
- Watchdog alert log (last 20 typed entries, filtering out `watchdog_summary`)
- Policy firing log (all time)
- Estate drift report (latest)

What it produces:
- Bottleneck analysis (same phase slow multiple times → high priority)
- Policy staleness detection (>3 untriggered policies → medium)
- Policy overlap detection (>2 co-firing contexts → medium)
- Outcome velocity diagnosis (0 velocity → critical; <1/day → medium)
- Domain coverage narrowness
- Recurring alert patterns from watchdog (reads `type` field — **must** be a real alert type, not `UNKNOWN` or `?`)
- High-fire policies (≥5 firings) that could be automated

Output: `~/.hermes/reports/estate-optimization.md`

**Key design decision:** Recommendations are ranked (critical > high > medium > low > info) and include an `action` slug for machine parsing. The report ends with an **Actions Required** checklist of all unique actions.

**Pitfall:** If the optimization report shows `"Alert type 'UNKNOWN' fired N times"`, the watchdog alert log has untyped entries. Clean them from the log file and check the watchdog's `main()` function is writing individual typed entries (not a lumped `"alerts"` array).

## Phase 4: Auto-Remediation

Script: `estate-auto-remediation.py`

**Currently dry-run only.** Preview what would happen; never executes without explicit user instruction.

Current capabilities:
- Archive policies with 0 hits that are 7+ days old (moves to `~/.hermes/policies/archived/`)
- Flag consolidation candidates (same domain → multiple policies)
- Clean watchdog alerts older than 7 days

Invocation:
```bash
python3 ~/.hermes/scripts/estate-auto-remediation.py --dry-run  # preview only
python3 ~/.hermes/scripts/estate-auto-remediation.py             # live (not yet safe for all scenarios)
```

Every action is logged to `~/.hermes/logs/remediation/actions.jsonl` with `dry_run: true/false` flag.

**Safety design:** Always creates a backup of any file it moves. Always logs before acting. The 7-day grace period prevents archiving young policies prematurely.

**Pitfall:** Always check for duplicate archive directories (`archived/` vs `_archived/`) after any policy archiving operation. Consolidate to `policies/archived/`. The `_archived/` directory can appear if a previous archiving operation created it and a later one ignored it.

## Orchestration: Full Pipeline Run

Script: `estate-full-run.sh`

Runs all 4 phases in sequence:
1. `estate-inventory.py` — snapshot (run with `2>/dev/null` to suppress stderr, confirm separately)
2. `estate-drift-detector.py` — compare to last baseline
3. `estate-optimization-scanner.py` — analyze pipeline outputs
4. `estate-auto-remediation.py --dry-run` — preview remediation

Output to Telegram via no-agent cron (the `estate-inventory-audit` job at 6am daily).

**Pitfall — output capture:** When `estate-inventory.py` runs inside the shell script, its stdout IS the report. Piping through `tail -1` or `grep` truncates the Telegram output. Fix: redirect stderr to `/dev/null` (`2>/dev/null`) and print a separate confirmation line.

**Pitfall — watchdog alert log format:** The optimization scanner reads the `type` field from `watchdog.jsonl`. If watchdog entries lack a `type` field (old format: lumped `{"alerts": ["CRON_ERROR: ..."]}`), the scanner reports `UNKNOWN`. After switching to typed alerts, clean the old untyped entries from the log file.

## Cron Integration

The estate pipeline runs as a no-agent cron job (`estate-inventory-audit`, job_id `c1a057d34b00`):
- Schedule: `0 6 * * *` (daily at 6am)
- Script: `estate-full-run.sh`
- Deliver: origin (Telegram)
- No model consumed (no-agent)

## When to Run Manually

- User asks "what changed in my estate" → run drift detector
- User asks "what needs optimization" → run optimization scanner
- User asks "what would happen if we cleaned up" → run remediation with `--dry-run`
- User asks "full stack audit" → run the full pipeline via `estate-full-run.sh`

## How the 8am Strategist and 9am Briefing Use This

The 6am estate pipeline writes `reports/estate-optimization.md`. The 8am strategist audit (`daily-strategist-audit` cron) should read this report, as should the 9am morning briefing. If the optimization report exists and has recommendations, the strategist should prioritize action items from it.

## Pitfalls (Earned in Production)

### Watchdog Alert Logging — Type Everything
The optimization scanner reads the `type` field from watchdog alerts to classify recurring issues. If watchdog logs alerts without a proper type field, the scanner reports `"Alert type 'UNKNOWN' fired N times"` — useless.

**Fix:** Every alert written to `watchdog.jsonl` MUST have a `type` field extracted from the alert prefix (e.g., `CRON_ERROR` from `"CRON_ERROR: foo barred"`). The watchdog's `log_alert()` function handles this, but check that the summary entry is also typed as `watchdog_summary`.

**Diagnostic:** If the optimization report shows `type: '?'` or `type: 'UNKNOWN'` for watchdog alerts:
1. Check `watchdog.jsonl` — do entries have a `type` field?
2. If not, the watchdog was writing lumped `{"alerts": ["CRON_ERROR: ..."]}` format instead of individual typed entries
3. Clean old untyped entries from the log file to prevent stale data from polluting analysis

### Inventory Output Capture
When running `estate-inventory.py` inside `estate-full-run.sh`, the script's stdout IS the report. If the shell pipes it through `tail -1` or `grep`, the inventory text in the Telegram output will be truncated.

**Fix:** Run `estate-inventory.py 2>/dev/null` (silences stderr) and print a confirmation message separately: `echo "(inventory written to reports/estate-inventory.md)"`.

### Archive Directory Consistency
The auto-remediation script and manual archival may produce duplicate archive directories (`_archived/` vs `archived/`). Always check both exist after any policy archiving operation. Standard name: `policies/archived/`.

### Policy Review: Don't Archive Unique Domains
When reviewing dead policies, a policy with 0 hits in a domain that has NO other active policies should be KEPT, not archived. Archiving it leaves a blind spot that won't be noticed for days. The concept may be valid; it needs more runway.

### Drift Detector — First Run Behavior
The drift detector's first run always produces `"First snapshot — baseline established"` which is an info message, not actual drift. The report file is created. On subsequent runs with no changes, no report is produced and the file is deleted. This is correct behavior — don't try to suppress the first run's output.

## Policy Review Methodology

This session produced a repeatable methodology for reviewing dead policies. See `references/policy-review-methodology.md` for the full framework (supersedence, domain coverage, rule coherence, confidence, and overlap checks).

**Critical lesson (source: correction 2026-06-18):** Never archive policies based on metadata alone — always read the rule text and compare trigger conditions. Two policies in the same domain may form an **escalation chain** rather than being duplicates. The chain pattern uses `escalates_to`, `supersedes`, `depends_on`, and `superseded_by` fields in policy JSON to make architectural intent explicit. The drift detector, optimization scanner, and auto-remediation all skip chain members from inactivity/archival checks.

## Escalation Chain Pattern (Added 2026-06-18)

When two or more policies in the same domain have related but distinct triggers, they can form a **tiered escalation chain**:

```
Tier 1: pol-003 (provisional) — "approach is clear from spec, execute"
Tier 2: pol-007 (active)      — "work is scoped + safe (money/identity/moat)"
Tier 3: pol-008 (active)      — "if corrected 2+ times, gate before clarify()"
```

Each tier has a different trigger, different severity. Tier 1 fires first; if the pattern repeats despite it, Tier 2 fires; if both fail, Tier 3 adds a structural gate.

The pipeline components were updated to respect this pattern:
- Drift detector: skips chain members from "policy never fired" warnings
- Optimization scanner: filters chain domains from overlap detection
- Auto-remediation: skips chain members from archival consideration

Key metadata fields:
```
escalates_to:    This policy is Tier N, escalate to the named policy
supersedes:      This is a stricter version of the named policy
depends_on:      This policy only fires if the named policy exists
superseded_by:   This policy has been superseded (points to the successor)
notes:           Human-readable description of the chain relationship
```

## References

- `references/estate-pipeline-architecture.md` — how the 4 phases interact, data flow, file dependencies
- `references/estate-first-audit-results.md` — the first run results (18 dead policies detected, overlapping domains identified)
- `references/policy-review-methodology.md` — structured framework for reviewing and archiving policies, including the 5-question decision checklist and common archival pitfalls
