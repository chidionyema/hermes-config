# Build Note 09 — Idle Continuous Learning

*Part of the Otto system. See 00-MASTER.md for the architectural context.*

## What it is

The combined pipeline that runs all three idle-time engines (consolidation, regression, gap-finding) on a timer, pre-emptible by real tasks, compute-capped.

## Orchestrator

**File:** `~/.hermes/scripts/idle-learning-run.sh`

**Scheduling:** Cron job `3fcdc6bd8859`, every 2h, no-agent mode.

**Pre-empt check:** Skips the run if gateway.log was modified in the last 5 minutes (user is active).

**Runtime cap:** 120 seconds max.

**Phase order:**
1. Policy consolidation (`idle-consolidation.py`)
2. Self-regression harvest + run (`self-regression.py --harvest && self-regression.py --report`)
3. Gap-finding (`gap-finding.py --report`)

## Convergence

All three engines operate on the task-performance layer only. None modifies the model, the reflection mechanism, or the evaluation criteria. All three are bounded (2-min max runtime, pre-emptible, compute-capped). They represent "continuous learning" as continuous sharpening of the existing ruleset and surfacing of gaps — not self-modification of how Otto learns.
