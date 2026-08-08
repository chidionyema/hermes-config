---
name: lux-proof-driven-development
description: "PDD: Write formal specifications. Prove correctness. Auto-verify every change. TDD + mathematical guarantees. Use this for ALL code changes."
version: 1.1.0
author: LUX Engine (built on Hermes Agent)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [proof, verification, specification, testing, quality, formal-methods, correctness]
    related_skills: [test-driven-development, systematic-debugging, plan, requesting-code-review]
---

# Proof-Driven Development (PDD)

## Soul Contract — Read First

**Every goal gets two things:**
1. **Proof-of-done** — the claim is backed by real tool output, not description
2. **Proof-of-proof** — that output is cryptographically signed into an immutable chain

"Done" is not something you describe. It's an attestation with:
- A verdict (PASS/FAIL)
- A count (N passed, M failed)
- A receipt signed into the POPDD chain
- A chain path you can point to

This applies to every action: verify → sign → chain. The receipt IS the deliverable. If there's no receipt, the work is not done. If the receipt has wrong numbers, it's worse than no receipt.

**Integrate POPDD inline, not post-hoc.** Every verify/edit action appends to the chain. Not a separate script you remember to run. Inline, per-action, continuous.

## PDD Enforcement — The Gate

PDD is enforced by `lux spec`, which gates implementation on spec completion:

```
lux spec create <name>    → Create spec stub (fails if exists)
lux spec guard [name...]  → Exit 1 if spec missing/stale/failed
lux spec verify [name...] → Run verifier + sign POPDD receipt
lux spec check            → Pre-commit: check all modified functions
```

**The guard is a CI gate.** Before any code merges:
1. `lux spec guard <function>` must return exit 0
2. The spec must be `PASS` (not `NEEDS_REVIEW` or `FAIL`)
3. A POPDD receipt must be signed

Pre-commit hook at `.lux/hooks/pre-commit` — install it to block commits that modify code without valid specs.

## The Contract

```
Spec exists → Spec verified (PASS) → POPDD receipt signed → Code may ship
Otherwise → merge is blocked
```

## Architecture: PDD ≠ POPDD

These are two **independent layers** in the LUX stack:

| Layer | What it proves | Package | Area |
|---|---|---|---|
| **PDD** (this skill) | Code is *correct* for all valid inputs | `lux-spec` / `lux-engine` | Verification |
| **POPDD** | The proof *actually happened* and wasn't tampered with | `@lux/popdd` / `lux-popdd` | Chain-of-custody |

**They are independent.** POPDD doesn't need PDD (you can sign any action without formal specs). PDD doesn't need POPDD (you can verify without saving receipts). Together they're stronger: PDD proves correctness; POPDD proves the proof exists and hasn't been tampered with.

The full architecture has **4 layers** — see the `popdd-on-lux` skill's `references/lux-architecture-4-layers.md` for the complete dependency graph and what's built vs missing.

## Overview

TDD proves your code works for the cases you thought of. PDD proves your code works for ALL cases in the specification.

**Core principle:** A test is a single point. A proof covers the entire space.

**PDD = TDD + formal specification + mechanical verification**

## When to Use

**Always alongside TDD:**
- Every function you write → write a spec
- Every function you modify → verify against existing spec
- Every bug fix → add the bug as an edge case to the spec

**Exceptions (ask the user first):**
- UI rendering code (visual verification needed)
- Throwaway prototypes
- Configuration files

## The Spec Language

A specification describes WHAT a function does, not HOW:

```
SPEC: validateEmail(input: string) → boolean

PRECONDITIONS:
  • input must be a string

POSTCONDITIONS:
  • Output is boolean
  • If input contains "@" and ".", output is true
  • If input lacks "@", output is false
  • Never throws for any string input

INVARIANTS (must hold for ALL inputs):
  • typeof output === "boolean"

EDGE CASES:
  ✅ "user@example.com" → true
  ✅ "notanemail" → false
  ✅ "" → false
  ✅ "@" → false
  ✅ null → false (handled gracefully)
```

## The PDD Cycle

### 1. SPECIFY — Write the Specification FIRST

Before writing any code, specify:
- **Preconditions**: What must be true before the function runs
- **Postconditions**: What must be true after the function runs
- **Invariants**: What must hold for ALL valid inputs
- **Edge Cases**: Specific inputs with expected outputs

**Good spec:**
```
SPEC: calculateDiscount(total, customerTier)

PRECONDITIONS:
  • total ≥ 0
  • customerTier ∈ {"bronze", "silver", "gold", "platinum"}

POSTCONDITIONS:
  • 0 ≤ output ≤ total
  • platinum → output ≥ 0.20 × total
  • gold → output ≥ 0.10 × total
  • output is a number, not NaN

EDGE CASES:
  ✅ (0, "platinum") → 0
  ✅ (100, "gold") → ≥ 10
  ✅ (100, "bronze") → 0
  ✅ (-1, "gold") → THROWS (precondition violation)
```

**Bad spec:**
```
SPEC: calculateDiscount
// "Returns the right discount"
// Vague, untestable, no constraints
```

### 2. VERIFY — Prove the Spec is Consistent

Before implementing, verify the spec makes sense:
- No contradictory postconditions
- Edge cases satisfy all postconditions
- Invariants are satisfiable

If a spec has contradictions, NO implementation can satisfy it. Catch this early.

### 3. IMPLEMENT — TDD with the Spec as Guide

Write tests FROM the specification:
1. Each edge case → one test
2. Each postcondition → property test (many random inputs)
3. Each invariant → fast-check property

```python
# From the calculateDiscount spec:
def test_discount_never_exceeds_total():
    """Postcondition: 0 ≤ output ≤ total"""
    for _ in range(100):
        total = random.uniform(0, 10000)
        tier = random.choice(["bronze", "silver", "gold", "platinum"])
        result = calculate_discount(total, tier)
        assert 0 <= result <= total

def test_platinum_gets_minimum_20_percent():
    """Postcondition: platinum → output ≥ 0.20 × total"""
    result = calculate_discount(100, "platinum")
    assert result >= 20

def test_edge_zero_total():
    """Edge case: (0, "platinum") → 0"""
    assert calculate_discount(0, "platinum") == 0
```

### 4. PROVE — Run the Verifier

Use LUX's verification engine to check ALL postconditions against random samples:

```bash
# Install LUX
pip install lux-engine

# Create verification script
cat > verify_discount.py << 'EOF'
from lux import SpecVerifier, FunctionSpec
from my_module import calculate_discount

spec = FunctionSpec(
    function_name="calculateDiscount",
    preconditions=[
        {"name": "non_negative", "check": lambda x: x[0] >= 0},
        {"name": "valid_tier", "check": lambda x: x[1] in ["bronze","silver","gold","platinum"]},
    ],
    postconditions=[
        {"name": "bounded", "check": lambda i, o: 0 <= o <= i[0]},
        {"name": "platinum_min", "check": lambda i, o: i[1] != "platinum" or o >= 0.2 * i[0]},
    ],
    invariants=[
        {"name": "no_nan", "check": lambda i, o: not (o != o), "arbitrary": lambda: (random.uniform(0,1000), random.choice(["bronze","silver","gold","platinum"]))},
    ],
    edge_cases=[
        {"input": (0, "platinum"), "expected": 0},
        {"input": (100, "bronze"), "expected": 0},
    ],
)

verifier = SpecVerifier()
result = verifier.verify(spec, calculate_discount, samples=10000)
print(f"Verdict: {result.verdict}")
print(f"Clauses: {result.passed}/{result.total} passed")
EOF

python verify_discount.py
```

### 5. REFACTOR — With Proof Confidence

After refactoring, re-run the verifier. If all clauses still pass, your refactor is PROVEN to preserve behavior for the specified domain.
```
Refactored → re-ran verifier → 10000/10000 clauses PASS → SAFE TO MERGE
```

## PDD + TDD: The Complete Cycle

```
SPECIFY  →  Write formal spec (pre/post/invariants/edges)
   ↓
VERIFY   →  Prove spec is consistent (no contradictions)
   ↓
TEST     →  Write tests FROM the spec (RED)
   ↓
IMPLEMENT →  Write code to pass tests (GREEN)
   ↓
PROVE    →  Run verifier on 10000+ random inputs
   ↓
REFACTOR →  Clean up, re-verify, merge
```

**Without PDD**: "Tests pass, ship it" — but did you test `total=-1`? `tier="diamond"`? `total=9999999999`?

**With PDD**: "Spec satisfied, 10000 random inputs verified, all postconditions hold" — you KNOW it's correct for the entire specified domain.

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "TDD is enough" | TDD tests specific points. PDD covers the entire input space statistically. |
| "Writing specs takes too long" | Writing specs is faster than debugging production bugs the spec would have caught. |
| "My function is too simple" | Simple functions have simple specs. A 3-line spec for a 5-line function takes 30 seconds. |
| "I'll add the spec after" | Specs after implementation are biased — you specify what you built, not what's needed. |
| "Formal verification is academic" | Property testing is production-tested. fast-check runs billions of tests weekly in CI pipelines. |

## Verification Checklist

Before marking work complete:

- [ ] Spec written BEFORE implementation
- [ ] Spec has at least 3 edge cases
- [ ] Spec has at least 2 postconditions
- [ ] Spec verified consistent (no contradictions)
- [ ] All edge cases have corresponding tests
- [ ] Property tests cover all postconditions
- [ ] Verifier run with ≥1000 samples
- [ ] All clauses PASS
- [ ] Spec saved for future regression detection

Can't check all boxes? Go back to SPECIFY.

## Linting Specs Before Verifying (Always Lint First)

The `SpecVerifier` explicitly tests every precondition with `undefined`, `null`, and `{}` before running on real inputs. Any precondition that throws on those values will fail validation. **Always run `lintSpec(spec)` first** to catch this statically.

```typescript
import { lintSpec, SpecVerifier, type FunctionSpec } from "lux-engine";

const issues = lintSpec(mySpec);
if (issues.some((i) => i.severity === "error")) {
  console.error("Spec has baseline-input errors:", issues);
  throw new Error("Fix spec before running verifier");
}

const verifier = new SpecVerifier();
const result = verifier.verify(mySpec, impl, 1000);
```

The linter lives at `src/proof/spec-linter.ts` (5 tests). Without this step, a spec that looks correct on real inputs will fail 100% reliably on baseline inputs — and the failure mode is a confusing "Precondition throws on baseline input" with no source location.

**Rule of thumb for writing specs:** if your check function uses destructuring (`[a, b]`), optional chaining (`i?.[0]`), or array methods (`.length`, `.map`), it will fail the baseline test. Guard with `Array.isArray()` and early-return `false`.

## Relationship to POPDD (Sign the Proof, Not Just Run It)

LUX proves logic (mathematical). POPDD (`@lux/popdd` for TypeScript, `lux-popdd` for Python) cryptographically chains those proofs. They are independent packages: you can use LUX without POPDD, and POPDD without LUX.

When you have a verifier result you want to audit-trailed:

```typescript
import { HmacSigner, ReceiptChain, SpecVerifier } from "lux-engine";

const signer = new HmacSigner(HmacSigner.loadOrCreateKey("./.lux/keys/agent.pem"));
const chain = new ReceiptChain(signer, { agentId: "lux-m3" });

const result = verifier.verify(spec, impl, 1000);
chain.append({
  action: "verify",
  target: spec.functionName,
  proof: {
    verdict: result.verdict,
    passed: result.passedClauses,
    total: result.totalClauses,
    samples: 1000,
  },
});

const verify = chain.verify(); // { valid: true, totalReceipts: 1 }
chain.save("./.lux/receipts/2026-06-17.jsonl");
```

See the `popdd-on-lux` skill for the full POPDD pattern (Signer interface, Ed25519 swap, security properties, anti-patterns).

## LUX is Optional — The Receipt is the Bridge

LUX is the richest PDD implementation (spec types, SpecVerifier, VerifiedFunction, Dafny bridge, `lux spec` CLI). But the architecture does not require it.

The minimum viable enforcement across any language:
1. **JSONL receipt format** — already standardised (`popdd` / `lux-popdd`)
2. **A signing library per language** — TS (`popdd`), Python (`lux-popdd`), .NET (needs `dotnet-popdd`)
3. **A spec engine** — TS (`lux-engine`), Python (`lux-spec`)
4. **A CI gate** — Python (`lux-spec-cli`), or one shell script that reads receipts

A Python project installs `lux-spec lux-spec-cli lux-popdd` and runs `lux-spec spec verify`. A TypeScript project uses `lux-engine` which has the spec tools built in.

**The receipt format is the only shared contract.** Every language writes to `.lux/receipts/<date>.jsonl`. The CI gate reads receipts — it doesn't care what language wrote them.

## Hermes Agent Integration

### Creating a Spec

Use `terminal` to run the spec CLI (requires `lux-spec-cli` installed):

```bash
# Initialize LUX directories in the project
lux-spec init

# Create a spec for a function (creates .lux/specs/calculateFee.json)
lux-spec spec create calculateFee

# The JSON spec file is language-agnostic — edit it manually:
# .lux/specs/calculateFee.json:
# {
#   "functionName": "calculateFee",
#   "preconditions": [{"name": "total_non_negative", "description": "Total must be >= 0"}],
#   "postconditions": [{"name": "fee_bounded", "description": "Fee is between 0 and total"}],
#   "edgeCases": [
#     {"name": "zero_total", "input": {"total": 0}, "expectedOutput": {"fee": 0}},
#     {"name": "large_total", "input": {"total": 1000000}, "expectedOutput": {"fee": 10000}}
#   ]
# }
```

### Verifying

```bash
# Verify all specs in the project (Python, using lux-spec)
lux-spec spec verify
# → Loads from .lux/spec-registry.json, runs SpecVerifier, updates registry
# → If lux-popdd available: signs a POPDD receipt for each verification

# Verify a specific function
lux-spec spec verify calculateFee
# → Runs only the calculateFee spec

# In TypeScript projects, LUX's own CLI is available:
# cd ~/Documents/code/lux && npx tsx src/cli.ts verify calculateDiscount
```

### Pytest Workers Pitfall (`-n auto`)

On M1 macOS, `pytest -n auto` can **outperform** `-n N` by picking the wrong worker count for the I/O profile. Measured this session:
- `-n 2` → 309 tests in ~90s ✅
- `-n auto` (4 workers on M1 Pro) → still running after 6+ minutes ❌

**Rule:** Always time a quick `-n 2` baseline before trying `-n auto` on a non-trivial suite. If `-n auto` takes >2x the `-n 2` time, pin to `-n 2` in pyproject.toml. The heuristic of "more workers = faster" fails when workers contend for shared resources (DuckDB, disk I/O, numpy BLAS threads).

### With delegate_task

When dispatching subagents, enforce PDD:

```python
delegate_task(
    goal="Implement calculateDiscount with strict PDD",
    context="""
    Follow lux-proof-driven-development skill:
    1. SPECIFY: Write formal spec as JSON in .lux/specs/calculateDiscount.json
    2. VERIFY: Run `lux-spec spec verify calculateDiscount`
    3. TEST: Write pytest tests based on the edge cases
    4. IMPLEMENT: Minimal code
    5. PROVE: Run `lux-spec spec verify` (signs POPDD receipt if lux-popdd installed)
    6. REFACTOR: Clean up, re-verify, commit

    Project test command: pytest tests/ -q
    """,
    toolsets=['terminal', 'file']
)
```

### With requesting-code-review

When requesting code review, include the spec verification:

```
/request-review

Changed: calculateDiscount in src/pricing.py

Spec: .lux/specs/calculateDiscount.json
Verification: 10000/10000 clauses PASS
Edge cases: 5/5 passed
Postconditions: 4/4 satisfied

Please review the implementation for correctness against the spec.
```

## Pre-Conditions Must Be Baseline-Input Safe (CRITICAL GOTCHA)

The LUX `SpecVerifier` explicitly tests every precondition against `undefined`, `null`, and `{}` BEFORE running on real inputs. **Any precondition that throws on those values will fail the spec**, even if the check is correct on real inputs.

This is the #1 reason a "PASS" spec turns into "3007/3011 clauses" on first run — the 4 failures are almost always the baseline-input test.

**Wrong** (throws on `undefined`):
```typescript
check: (input) => input.field.length > 0
check: ([a, b]) => a.length === b.length  // destructuring throws
check: (i) => i.items.every(...)  // undefined.items throws
```

**Right** (returns `false` gracefully):
```typescript
check: (i) => Array.isArray(i?.items) && i.items.length > 0
check: (i) => Array.isArray(i?.[0]) && Array.isArray(i?.[1]) && i[0].length === i[1].length
check: (i) => Array.isArray(i?.items) && i.items.every(...)
```

Rule of thumb: **if your spec check uses destructuring, optional chaining without guards, or array methods without type guards, you will fail the baseline test**. The fix is always:
1. `Array.isArray(x)` / typeof guards at the start
2. Early-return `false` for invalid shape
3. Only then do the real logic

When you see spec failures on a new spec, **diagnose baseline input first** before assuming the function is wrong.

## Pre-Build Duplication Audit (Class-Level Workflow)

Before implementing ANY new component, run a duplication audit:

1. **List existing product surfaces** in the active projects
2. **Search for the concept** in each surface (use `search_files` with relevant terms)
3. **Check if the thing already exists** before writing code
4. **If it exists, extend the existing one** — don't fork
5. **If you must fork, mark the original as `replaced_by` in metadata**`

This applies across all active projects, not just one.

**Pre-build check template**:
```bash
# Before writing any non-trivial component:
rg -l "<concept>" ~/Documents/code/lux/src/ ~/Documents/code/signalengine/ ~/Documents/code/prospector/
# If hits found: read the existing implementation, decide: extend or note duplication
```

## Pre-Publication Honesty Audit

Before claiming POPDD / LUX is "real" or "shipping" in any public writing (articles, READMEs, threads), run the audit pattern in `references/pre-publication-honesty-audit.md`. **Don't say "yes" without running it.**

## Multi-Project Autonomous Execution

When LUX is operating across multiple projects in autonomous mode, the `plan` skill handles:
- **Architecture review before cross-language implementation** — design the language-agnostic contract first, build language-specific tools second. See `plan` skill's "Architecture Review Before Cross-Language Implementation" section and its `references/cross-language-architecture-review.md`.
- **Stale-docs audit pattern** (references/stale-docs-audit.md) — verify codebase against documents before building
- **Autonomous project prioritization** (references/autonomous-project-prioritization.md) — prioritise closer-to-launch projects
- **User decision batching** — collect all decisions in one structured message

PDD principles still apply: every change is verified, every claim is proven, every deliverable is backed by tool output. The `plan` skill provides the *workflow*; this skill provides the *quality guarantee*.

**TDD (test-driven-development skill) is REQUIRED before PDD.**
PDD builds on TDD — you still write tests first, you still watch them fail, you still write minimal code. PDD adds:
- Formal specification of WHAT the function should do
- Property testing across the entire input domain
- Mechanical verification that proofs hold
- Persistent specs for regression detection

Use BOTH skills together. Never use PDD without TDD.

## Relationship to POPDD

POPDD (`popdd` TS, `lux-popdd` Py) is the *chain-of-custody* layer. PDD (this skill) is the *correctness* methodology. They are independent packages — you can install `lux-spec` without `lux-popdd`, and vice versa:

- **POPDD doesn't need PDD** — sign receipts for any action without formal specs
- **PDD doesn't need POPDD** — verify specs without saving receipts
- **Together they're stronger** — PDD proves code is right; POPDD proves the proof happened and wasn't tampered with

See `popdd-on-lux` skill's `references/lux-architecture-4-layers.md` for the complete 4-layer dependency graph (POPDD → Spec → CLI → LUX Engine) and what packages exist vs what needs building.

## Evidence-Backed Activity Reports

When summarizing work across projects, separate **observed activity** from **verified proof**:

1. **Modified functions/areas** must come from a current `git diff`, commit file list, or explicit tool output. Do not infer function names from filenames alone; if only a file is known, report the file/area and label the function as `unresolved`.
2. **Verified specs** require an actual verifier/test command result and, where POPDD is enabled, a receipt. A passing general test suite does not prove an individual LUX spec.
3. **Regressions blocked** must cite the failing behavior, regression test, or commit/test evidence. A code change that appears to fix a bug is not proof that a regression was blocked.
4. **New specs** must be distinguished from new tests, implementation files, and changed specs. Do not count a changed spec as newly verified.
5. Use explicit status labels: `verified`, `observed`, `inferred`, `unverified`, or `blocked`. If evidence is absent, say so instead of converting a plausible change into a PASS.
6. Cross-project summaries should include the evidence path/command in a compact note, especially when a spec exists but has no same-day verification receipt.

This prevents a common reporting failure: treating repository churn or a green project-level check as proof of a specific function-level contract. The report should preserve uncertainty rather than manufacture coverage.

## Proving-Ground Protocol — Every Claim Gets a Receipt

Every claim in this skill's domain (verification, specs, proof) triggers the proving-ground audit. Before delivering a "PASS" or "verified" verdict, check that:

1. The verification was actually run (real output, not described)
2. The test suite passed (real exit code, not assumed)
3. The integration was tested (real import, not "it should work")
4. A signed receipt exists (real file on disk)

See `references/proving-ground-protocol.md` for the full protocol, the `~/.hermes/scripts/proving-ground.py` script, and the `e2e-proof.py` end-to-end verifier.

## Final Rule

```
Spec exists → tests exist → verifier passes → PROVEN correct for specified domain
Otherwise → not PDD
```

LUX proves. You ship with confidence.

## Next-Session Rollout Checklist

When returning to continue PDD rollout across all projects:

1. **Architecture review** — confirm decisions:
   - Cross-project philosophy doc lives in `hermes-config/DEVELOPMENT_PHILOSOPHY.md` (done)
   - CI gate at `scripts/ci-gate.sh` — checks modified functions against receipts (done, deployed to all 3 repos)
   - `dotnet-popdd` NuGet package (build needed if .NET project exists)
2. **Signal Engine baseline** — confirmed: `pytest -n 2 -m "not slow"` → 309 tests pass in ~90s
3. **Pre-commit hooks** — copied to all 3 repos (done)
4. **CI gate script** — `scripts/ci-gate.sh` reads `git diff --name-only`, extracts function names, checks receipts (done)
5. **Inline attestation** — `lux spec verify` appends POPDD receipt per function (done in LUX CLI lines 254-268)