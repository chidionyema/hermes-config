# Otto System — Specification Suite

> Complete architectural documentation for the Otto autonomous project coordinator.
> All 10 build notes, indexed from the master architecture document.

## Table of Contents

| # | Spec | Covers | Script(s) |
|---|------|--------|-----------|
| 00 | [MASTER](00-MASTER.md) | Architecture spine, L0-L5 layers, data flow, convergence proof, file map | All |
| 01 | [Correction-Learning Loop](01-correction-learning-loop.md) | Policy lifecycle, runtime enforcement, post-correction protocol | `policy-enforcer.py`, `reflect-on-correction.py`, `otto-learn.py` |
| 02 | [Dispatch Gate](02-dispatch-gate.md) | Structural pre-commit gate against permission-asking | `dispatch_gate.py` |
| 03 | [Memory Retrieval](03-memory-retrieval.md) | Self-query routing with confidence scoring, policy injection | `memory_retrieval.py` |
| 04 | [Idle Consolidation](04-idle-consolidation.md) | Merge/retire/flag policies during idle | `idle-consolidation.py` |
| 05 | [Self-Regression](05-self-regression.md) | Failure corpus, regression testing, coverage tracking | `self-regression.py` |
| 06 | [Gap-Finding](06-gap-finding.md) | Domain scan, build candidate surfacing | `gap-finding.py` |
| 07 | [DNA Specimen](07-dna-specimen.md) | Reasoning invariants adapted from Prospector | — |
| 08 | [Goetic Piece](08-goetic-piece.md) | Boundaries, off-switch, convergence guarantee, safety mechanisms | `meta-improver.py` (safety) |
| 09 | [Idle Continuous Learning](09-idle-continuous-learning.md) | Combined pipeline, scheduling, pre-empt, compute cap | `idle-learning-run.sh` |
| 10 | [Exponential Self-Improvement](10-exponential-self-improvement.md) | Compounding improvement velocity, meta-improver architecture | `meta-improver.py` |

## Recommended reading order

1. `00-MASTER.md` — start here for the big picture
2. `01-correction-learning-loop.md` — the core loop that everything else builds on
3. `08-goetic-piece.md` — the boundaries (understand safety before adding power)
4. `02-dispatch-gate.md` + `03-memory-retrieval.md` — the runtime infrastructure
5. `04-06` — the idle-time engines (consolidation, regression, gap-finding)
6. `09-idle-continuous-learning.md` — how they're wired together
7. `10-exponential-self-improvement.md` — the meta layer (requires understanding everything below)
8. `07-dna-specimen.md` — can be read at any time (it's the reasoning culture, not an implementation spec)

## File map

```
~/.hermes/
├── specs/otto-system/          ← This directory (10 specs + README)
├── scripts/                    ← 13 Python/shell scripts implementing the specs
│   ├── policy-enforcer.py      ← 01: Runtime enforcement
│   ├── dispatch_gate.py        ← 02: Pre-commit permission gate
│   ├── memory_retrieval.py     ← 03: Self-query routing
│   ├── idle-consolidation.py   ← 04: Policy maintenance
│   ├── self-regression.py      ← 05: Failure regression
│   ├── gap-finding.py          ← 06: Domain gap detection
│   ├── idle-learning-run.sh    ← 09: Orchestrator
│   ├── meta-improver.py        ← 10: Exponential lever
│   ├── reflect-on-correction.py ← 01: Post-correction hook
│   ├── otto-learn.py           ← 01: Policy CLI
│   ├── daily_reflection.py     ← L4: 6pm cron
│   ├── launch-report.sh        ← Health report
│   └── hourly_pulse.sh         ← Hourly improvement pulse
├── policies/                   ← 8 correction policies (JSON)
├── logs/                       ← Policy firings, reflections, maintenance reports
├── skills/                     ← Operating model + custom skills
└── meta/                       ← Exponential architecture (OFF_SWITCH, snapshots, configs)
```
