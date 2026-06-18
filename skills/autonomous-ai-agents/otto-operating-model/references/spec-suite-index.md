# Otto Spec Suite — Quick Index

The full system specification lives at `~/.hermes/specs/otto-system/`. Read the relevant spec for any design question.

| Spec | File | What it covers | When to read |
|------|------|----------------|-------------|
| Master | `00-MASTER.md` | Architecture spine L0-L5, data flow, convergence proof, file map | Before any Otto-system work |
| Correction-Learning Loop | `01-correction-learning-loop.md` | Policy lifecycle, otto-learn, policy-enforcer, post-correction protocol | When adding/changing a policy |
| Dispatch Gate | `02-dispatch-gate.md` | Pre-action gate design, why patterns failed, why resource-classification works | When a question slips past the enforcer |
| Memory Retrieval Phase 1 | `03-memory-retrieval-phase1.md` | Tag schema, self-query routing, injection logging | When debugging strategist context |
| Idle Consolidation | `04-idle-consolidation.md` | Merge/retire/flag policies during idle | When running idle-consolidation.py |
| Self-Regression | `05-self-regression.md` | Failure corpus, regression testing against policies | When running self-regression.py |
| Gap-Finding | `06-gap-finding.md` | Capability registry scan, build candidate surfacing | When running gap-finding.py |
| DNA Specimen | `07-dna-specimen.md` | Reasoning DNA — invariants adapted from Prospector | When questioning Otto's reasoning approach |
| Goetic Piece | `08-goetic-piece.md` | Invariants, boundaries, off-switch, convergence guarantee | When a change threatens the convergence proof |
| Idle Continuous Learning | `09-idle-continuous-learning.md` | Combined idle pipeline: scheduling, pre-empt, compute cap | When modifying idle-learning-run.sh |

## Key Design Documents Outside the Spec Suite

| File | Covers |
|------|--------|
| `~/.hermes/specs/policy-enforcer-redesign.md` | Why the old pattern-list approach failed and how resource-classification fixes it structurally |
| `~/.hermes/reports/hermes-setup-audit-2026-06-18.md` | Full system audit — architecture, deps, state, integrations, cron, unknowns |

## Implementation Files (scripts)

| File | Connects to spec |
|------|------------------|
| `~/.hermes/scripts/policy-enforcer.py` | 01, 02 |
| `~/.hermes/scripts/memory_retrieval.py` | 03 |
| `~/.hermes/scripts/idle-consolidation.py` | 04 |
| `~/.hermes/scripts/self-regression.py` | 05 |
| `~/.hermes/scripts/gap-finding.py` | 06 |
| `~/.hermes/scripts/reflect-on-correction.py` | 01 |
| `~/.hermes/scripts/idle-learning-run.sh` | 09 |
