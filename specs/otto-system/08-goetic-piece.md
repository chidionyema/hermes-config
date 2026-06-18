# Build Note 08 — Goetic Piece

*Part of the Otto system. See 00-MASTER.md for the architectural context.*

## What it is

The boundaries, invariants, and off-switch that keep Otto convergent and auditable. Named for the Goetic tradition of containment — the system is powerful by design but its boundaries are defined, enforced, and non-negotiable.

## Non-Negotiable Boundaries

1. **The improver is human-controlled and fixed.** Policies improve within a fixed architecture. The architecture itself (policy-enforcer.py, reflect-on-correction.py, self-regression.py) changes via git commits, not runtime self-modification.

2. **Circular self-reference is prevented.** `meta-improver.py` computes its own SHA-256 hash at startup. If the file changed since the last audit, it aborts. The evaluator can never evaluate itself.

3. **Off-switch exists.** `~/.hermes/meta/OFF_SWITCH` file. If deleted, all automatic learning stops. The meta-improver checks this file before every action.

4. **Rollback mechanism exists.** Every meta-improver change records a before/after snapshot with a rollback command. Snapshots kept for 30 days.

5. **Audit trail is append-only.** `~/.hermes/logs/meta-improver/audit-index.jsonl`. Every change logged with timestamp, what changed, before/after hash, and reason.

## Convergence Proof

The system converges because:
- Each correction adds at most one policy
- Each idle run removes at most N policies (retirement)
- The evaluator (meta-improver) cannot modify the safety rules (hardcoded in source)
- The SHA-256 hash prevents circular evaluation
- Net policy count cannot grow unbounded because dead policies are retired

## What would make this system go exponential

Removing any of these three: off-switch, rollback, or the circular-self-reference hash. If all three are gone, the meta-improver could theoretically modify its own evaluation criteria, producing unbounded recursion. This is prevented by design.
