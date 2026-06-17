---
name: popdd-experiment
description: ARCHIVED — Python prototype of POPDD DecisionReceipts. SUPERSEDED by the TypeScript implementation in ~/Documents/code/lux/src/proof/receipt.ts (73/73 tests passing, 0 type errors). Do not use this Python version.
status: archived
archived_date: 2026-06-17
replaced_by: ~/Documents/code/lux/src/proof/receipt.ts + ~/Documents/code/lux/tests/receipt.test.ts
---

# POPDD — Proof of Proof-Driven Development

**Acronym:** POPDD (POPDD > PDD > TDD)
**Core claim:** "We don't test. We prove. And then we prove the proof."

## Architecture

Three layers, each proving the one below:

```
Level 3: Cryptographic Decision Receipts
         HMAC(proof_hash || agent_id || timestamp || parent_receipt)
         → chain of auditable, tamper-evident receipts
         This is the PROOF OF PROOF.

Level 2: Executable Proof Engine
         Checks FormalSpecs against runtime context
         → structured ProofResult with full evidence trace
         This is the PROOF.

Level 1: Formal Specifications
         Preconditions, postconditions, invariants, bounds
         → machine-readable contract for a behavior
         This is THE SPEC.
```

## Proof of Proof (POPDD) Explained

The cryptographic Decision Receipt is the key innovation:

1. **Agent executes a step** (runs a proof check, generates code, routes a decision)
2. **ProofEngine checks the FormalSpec** → produces a `ProofResult` (pass/fail + evidence)
3. **DecisionReceipt wraps the result** → HMAC binds `(proof_hash, agent_id, timestamp, parent_hash)`
4. **Receipts chain together** → `receipt_1 → receipt_2 → receipt_3`
5. **Tampers break the chain** → any modification invalidates the HMAC, and broken links propagate

This means you can:
- Verify a multi-step agent workflow in one shot (just call `receipt_N.verify()`)
- Prove the agent never deviated from its spec even if you don't trust the agent
- Detect tampering retroactively

## Files

### `popdd_experiment.py` — Runnable experiment

Contains:
- `FormalSpec` — spec language (preconditions, postconditions, invariants, bounds)
- `ProofEngine` — checks specs against context, returns `ProofResult`
- `DecisionReceipt` — cryptographic wrapping with HMAC-SHA256 chain
- 3 built-in specs:
  - `signal-engine/determinism` (T-DET: two runs, identical hash)
  - `signal-engine/backtest-integrity` (cost model, no LLM, OOS reporting)
  - `prospector/source-or-die` (every claim cites a source)
- Full experiment runner with violation-injection tests

## How to Run

```bash
cd /Users/chidionyema/Documents/code/signalengine
uv run python popdd_experiment.py
```

Expected output: `POPDD Layer Operational: ✅ YES` with all 8 checks passing.

## Verification Protocol

Before productionising a POPDD spec:

1. **Write the spec** — FormalSpec with pre/post/invariant/bounds
2. **Run against known-clean context** → must PASS
3. **Inject a violation** → must FAIL
4. **Generate receipt chain** → must verify
5. **Tamper with any link** → chain must break
6. **Only then** wire it into the production pipeline

## Integration Points

### Signal Engine
- Replace manual T-DET determinism check with `FormalSpec("signal-engine/determinism")`
- Add receipt generation to `run_m1.py` on every end-to-end run
- Receipts stored alongside `store/` data for auditable backtest runs

### Prospector
- Wrap `verify.py` verification runs in a DecisionReceipt chain
- Add receipts to every published dossier (proves the engine ran the full kill-check path)
- Store receipt hashes alongside `store/dossiers/` for dispute resolution

### Cryptographic Notes
- Receipts use HMAC-SHA256 with a context-derived key (reproducible)
- Production: use a real secret key from env, not a derived one
- For distributed use: sign with Ed25519 instead of HMAC for public verifiability
- The hash chain is O(n) to verify — fine for agent workflows, not for global consensus

## Current Status

✅ POPDD layer operational as of 2026-06-17.
- Determinism invariant: proven and receipted
- Multi-step chain: verified and tamper-resistant
- Source-or-die invariant: proven and violation-catching
- Integration into Signal Engine and Prospector pipelines: TODO
