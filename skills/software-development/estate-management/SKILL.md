---
name: estate-management
description: "Estate lifecycle: inventory, drift detection, optimization scanning, auto-remediation, and daily audit cadence for complex Hermes configurations. Covers the full pipeline from cataloging components to executing improvements."
version: 1.0.0
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

## Phase 3: Optimization Scanner

Script: `estate-optimization-scanner.py`

Reads ALL existing pipeline outputs and synthesizes them into ranked recommendations:

Sources consumed:
- Meta-improver bottleneck reports (last 5)
- Near-miss analysis (latest)
- Trend analysis (latest)
- Watchdog alert log (last 10)
- Policy firing log (all time)
- Estate drift report (latest)

What it produces:
- Bottleneck analysis (same phase slow multiple times → high priority)
- Policy staleness detection (>3 untriggered policies → medium)
- Policy overlap detection (>2 co-firing contexts → medium)
- Outcome velocity diagnosis (0 velocity → critical; <1/day → medium)
- Domain coverage narrowness
- Recurring alert patterns from watchdog
- High-fire policies (≥5 firings) that could be automated

Output: `~/.hermes/reports/estate-optimization.md`

**Key design decision:** Recommendations are ranked (critical > high > medium > low > info) and include an `action` slug for machine parsing. The report ends with an **Actions Required** checklist of all unique actions.

## Phase 4: Auto-Remediation

Script: `estate-auto-remediation.py`

**Currently dry-run only.** Preview what would happen; never executes without explicit user instruction.

Current capabilities:
- Archive policies with 0 hits that are 7+ days old (moves to `~/.hermes/policies/_archived/`)
- Flag consolidation candidates (same domain → multiple policies)
- Clean watchdog alerts older than 7 days

Invocation:
```bash
python3 ~/.hermes/scripts/estate-auto-remediation.py --dry-run  # preview only
python3 ~/.hermes/scripts/estate-auto-remediation.py             # live (not yet safe for all scenarios)
```

Every action is logged to `~/.hermes/logs/remediation/actions.jsonl` with `dry_run: true/false` flag.

**Safety design:** Always creates a backup of any file it moves. Always logs before acting. The 7-day grace period prevents archiving young policies prematurely.

## Orchestration: Full Pipeline Run

Script: `estate-full-run.sh`

Runs all 4 phases in sequence:
1. `estate-inventory.py` — snapshot
2. `estate-drift-detector.py` — compare to last baseline
3. `estate-optimization-scanner.py` — analyze pipeline outputs
4. `estate-auto-remediation.py --dry-run` — preview remediation

Output to Telegram via no-agent cron (the `estate-inventory-audit` job at 6am daily).

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

## References

- `references/estate-pipeline-architecture.md` — how the 4 phases interact, data flow, file dependencies
- `references/estate-first-audit-results.md` — the first run results (18 dead policies detected, overlapping domains identified)
