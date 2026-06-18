# Otto System — Master Specification

> Architectural spine of the autonomous project coordinator.
> All build notes reference this document. Read this before reading any individual spec.

## 1. System Identity

**Otto** is an autonomous engineering coordinator built on Hermes Agent. It coordinates across three projects (Signal Engine, LUX, Prospector) without waiting for instructions.

**What it is:** A rules-based, convergent self-improvement agent that sharpens its behaviour policies over time through bounded feedback loops.

**What it is NOT:** A self-modifying AGI. Otto never rewrites its own improvement mechanism. The improver is human-controlled and fixed. All learning is bounded to the task-performance layer — making better decisions within a fixed architecture, not changing the architecture itself.

## 2. Architecture Layers

Otto is organised in concentric layers from innermost (core capability) to outermost (monitoring and boundary):

### L0 — Hermes Core
The existing Hermes Agent framework. Provides:
- Gateway (Telegram) integration
- Subagent delegation
- File I/O, terminal, browser
- Memory system (MEMORY.md + USER.md, 2200/1375 char caps)
- Session database (SQLite, 25MB)
- Cron scheduler
- LSP integration (5 language servers)
- Everything in `~/.hermes/hermes-agent/`

### L1 — Operating Model (SKILL.md)
Located at `~/.hermes/skills/autonomous-ai-agents/otto-operating-model/SKILL.md`. Defines:
- Model tiering: Hermes (control loop) → Claude (strategist) → Minimax (executor)
- Default behaviour hierarchy: ACT (default) before REPORT before QUESTION
- Task dispatch rules: at dispatch time, decide if result is ACT, REPORT, or SURFACE
- Communication tone: never wait, always act, be specific, show evidence

### L2 — Correction-Learning Loop
The dynamic policy system. When the user corrects Otto:
1. `otto-learn add` writes a structured policy JSON to `~/.hermes/policies/`
2. `policy-enforcer.py` reads all active policies at action time and blocks violations
3. `reflect-on-correction.py` appends analysis to the daily reflection
4. Policies start provisional (confidence 0.3), promote on hits >= 3 and helped > hurt
5. Retire on helped/hurt ratio < 0.4

### L3 — Idle Continuous Learning
Three engines that run during idle (every 2h, pre-emptible by real tasks):
- **Consolidation:** Merge duplicates, retire dead policies, flag contradictions
- **Regression:** Test the current policy set against a corpus of past failures
- **Gap-finding:** Scan failure domains for missing skills/policies, surface as build candidates

### L4 — Monitoring & Cadence
- 9am daily: Morning briefing + project health + asks for priorities
- 6pm daily: Self-reflection + improvement plan
- Hourly: Config auto-push to GitHub
- Every 2h: Idle continuous learning
- Every 6h: Uncommitted work watch (silent unless >10 files)
- Weekly: LUX verify across all projects

### L5 — Off-Switch & Boundary
- The improver model is human-controlled and fixed
- Policies live on disk in a flat JSON directory — no self-referential improvement
- The convergence proof: each loop iteration sharpens the existing ruleset through a static evaluator; the evaluator is never itself evaluated
- All three idle features operate on the task-performance layer only; none touches the reflection mechanism, evaluation criteria, or model selection logic

## 3. Data Flow

```
User correction → otto-learn add → policy JSON → policy-enforcer reads at action time
                                                          ↓
                                              BLOCKED → apply rule
                                              PASS → proceed
                                                          ↓
                                              reflect-on-correction → daily reflection
                                                          ↓
                                              idle consolidation → merge/retire/flag
                                              idle regression → test corpus against policies
                                              idle gap-finding → surface uncovered domains
                                                          ↓
                                              next correction → loop repeats with sharper policies
```

## 4. Convergent Learning Proof

Otto's learning curve converges for three structural reasons:

1. **Fixed evaluation:** The improver (reflect-on-correction.py) uses a static template with fixed fields. It never changes its own evaluation criteria.
2. **Flat policy store:** Policies are JSON files on disk. No policy can modify the policy store structure, the reading mechanism, or the evaluation thresholds.
3. **Bounded improvement:** Each correction adds at most one policy. Each idle run removes at most N policies (retirement/merger). The net policy count cannot grow unbounded because dead policies are retired.

To go exponential, Otto would need to modify `policy-enforcer.py` or `reflect-on-correction.py` — both of which are human-audited and change via git commits, not runtime self-modification.

## 5. File Map

| File | Layer | Purpose |
|------|-------|---------|
| `~/.hermes/skills/autonomous-ai-agents/otto-operating-model/SKILL.md` | L1 | Operating model — all behaviour rules |
| `~/.hermes/policies/pol-*.json` | L2 | Correction policies (8 active) |
| `~/.hermes/scripts/otto-learn.py` | L2 | CLI for policy management |
| `~/.hermes/scripts/policy-enforcer.py` | L2 | Runtime enforcement — blocks violations before they happen |
| `~/.hermes/scripts/reflect-on-correction.py` | L2 | Post-correction analysis → daily reflection |
| `~/.hermes/scripts/dispatch_gate.py` | L1 | Pre-ask guard — blocks permission-asking language |
| `~/.hermes/scripts/idle-consolidation.py` | L3 | Merge/retire/flag policies |
| `~/.hermes/scripts/self-regression.py` | L3 | Re-run past failures against current policies |
| `~/.hermes/scripts/gap-finding.py` | L3 | Scan failure domains for missing coverage |
| `~/.hermes/scripts/idle-learning-run.sh` | L3 | Orchestrator — runs all 3 idle engines |
| `~/.hermes/scripts/daily_reflection.py` | L4 | 6pm cron — self-reflection |
| `~/.hermes/scripts/memory_retrieval.py` | L2/4 | Self-query routing + policy injection for strategist calls |
| `~/.hermes/logs/policy-firings.jsonl` | L2 | Every policy fire event |
| `~/.hermes/logs/injection-log.jsonl` | L2/4 | Every strategist injection |
| `~/.hermes/logs/reflection/YYYY-MM-DD.md` | L4 | Daily self-reflection |
| `~/.hermes/logs/maintenance/` | L3 | Consolidation + gap-finding reports |
| `~/.hermes/specs/otto-system/` | L0 | This specification suite |
| `~/.hermes/cron/jobs.json` | L4 | All scheduled jobs (7 active) |
