---
name: popdd-on-lux
description: "Add POPDD (Proof of Proof-Driven Development) DecisionReceipts to any project. Cryptographically chain agent actions to verification results using the @lux/popdd (TypeScript) or lux-popdd (Python) packages. Use when an agent's actions need an audit trail that can detect tampering, prove chain-of-custody, or be exported for compliance. Covers: installation, signer setup, chain construction, verification, tamper detection, Ed25519 swap, integration with SpecVerifier/Dafny, and the baseline-input spec trap."
---

# POPDD — Cryptographic Chain-of-Custody for Agent Actions

## What This Solves

You have an agent that performs actions (verify, edit, deploy, publish). You need a tamper-evident audit trail that proves:
1. **What** action was performed
2. **What** the proof payload was (verification result, hash, evidence)
3. **Who** performed it (agent identity)
4. **In what order** (sequence)
5. **That no one tampered** with the chain

POPDD is the **cryptographic foundation** (Layer 1) in the 4-layer LUX architecture. It knows nothing about specs or verification — it only signs JSON. See `references/lux-architecture-4-layers.md` for the complete 4-layer dependency graph.

POPDD is shipped as **two independent packages** with a shared API:
- **`popdd`** (TypeScript / Node) — `~/Documents/code/popdd-ts/`
- **`lux-popdd`** (Python) — `~/Documents/code/popdd-py/`

## The Full Architecture (4 Independent Layers)

| Layer | What | Package | Language | Status |
|---|---|---|---|---|
| **1. POPDD** | Cryptographic chain-of-custody | `popdd` / `lux-popdd` | TS + Py | ✅ Built, 18+21 tests pass |
| **2. Spec Engine** | Formal spec + verification | `lux-spec` | Python | ✅ Built, 53 tests pass (~/Documents/code/lux-spec-py/) |
| **3. Spec CLI** | CI gate — `lux-spec [init\|spec create\|verify\|guard\|check]` | `lux-spec-cli` | Python | ✅ Built, 14/17 tests pass (~/Documents/code/lux-spec-cli/) |
| **4. LUX Engine** | Full PDD platform (semantic graph, type-level proofs, Dafny) | `lux-engine` | TypeScript | ⚠️ Not published; depends on `popdd` (~/Documents/code/lux/) |

**Key design rule: no layer depends on another.** POPDD (Layer 1) doesn't know about specs. lux-spec (Layer 2) doesn't know about POPDD. Only the CLI (Layer 3) or an explicit integration script combines them.

`popdd_agent.py` (the hot-chain inline attestation module) now ships **inside** `lux-popdd` as `from popdd.agent import PopddAgent`. The old standalone copies in every project have been replaced with backward-compat re-export shims.

## When to Use

- Auditable AI coding workflows (every function edit produces a receipt)
- Compliance/regulatory contexts (SOC2, financial, legal)
- Multi-agent collaboration (track which agent did what)
- Supply-chain integrity (sign every build artifact)
- Any place where a log file isn't enough

## Architecture: Language-Agnostic Contract

The POPDD receipt format is the bridge across languages:

```
.lux/receipts/<date>.jsonl
Each line: {action, target, proof, contentHash, previousHash, signature}
```

Every language writes the same JSONL format. The CI gate reads only receipts — it doesn't care what language wrote them.

**Three language implementations exist or are needed:**

| Language | Package | Status | What it provides |
|----------|---------|--------|------------------|
| TypeScript | `@lux/popdd` (npm) | ✅ Deployed | `HmacSigner`, `ReceiptChain`, `DecisionReceipt` |
| Python | `lux-popdd` (PyPI) + `popdd_agent.py` | ✅ Deployed | Same API + hot-chain auto-save agent wrapper |
| .NET / C# | (none yet) | ❌ Need | NuGet package with `HmacSigner` + `ReceiptChain` |

**When adding a new language, don't port the entire PDD toolchain.** Port only the receipt chain (`HmacSigner` + `ReceiptChain` + JSONL save/load). Each language keeps its own spec format (TS `FunctionSpec`, Python dataclasses, C# attributes). The receipt IS the shared contract.

## Architecture

```
┌──────────────────────────────────────────────────────┐
│ ReceiptChain (one per session/run)                   │
│                                                      │
│  Receipt 0 (GENESIS)  →  Receipt 1  →  Receipt 2     │
│  contentHash: a3f2b1  →  hash: 8c4e9d  →  hash: ... │
│  signature: ed25a1    →  sig: 7fb02c  →  sig: ...    │
│       ↑                  ↑                ↑          │
│   HMAC-SHA256         chained to       chained to    │
│   with agent key      previous         previous      │
└──────────────────────────────────────────────────────┘
```

## Installation

### TypeScript (LUX and any Node project)

```bash
npm install popdd
```

**Note:** The package was originally under `@lux` scope but is now unscoped `popdd` to make it a general-purpose tool. The LUX repo references it as `"popdd": "file:../popdd-ts"` in package.json (local development path until npm published). The source repo is `chidionyema/popdd-ts`.

### Python (Signal Engine, Prospector, any Python project)

```bash
pip install lux-popdd lux-spec lux-spec-cli

# Local file path (during development, for sibling repos)
# In your pyproject.toml dependencies:
"lux-popdd @ file:///Users/chidionyema/Documents/code/popdd-py"
# (For hatchling projects, also add:)
# [tool.hatch.metadata]
# allow-direct-references = true
```

For `requirements.txt`:
```
lux-popdd @ file:///Users/chidionyema/Documents/code/popdd-py
```

For `uv` projects (e.g., Signal Engine):
```bash
uv pip install -e ../popdd-py
```

## Quick Start — TypeScript

```typescript
import { HmacSigner, ReceiptChain } from "popdd";

const signer = new HmacSigner(
  HmacSigner.loadOrCreateKey("~/.lux/keys/agent.pem")
);
const chain = new ReceiptChain(signer, { agentId: "lux-m3" });

chain.append({
  action: "verify",
  target: "calculateDiscount",
  proof: { verdict: "PASS", passed: 10000, total: 10000 },
});

chain.append({
  action: "edit",
  target: "src/pricing.ts",
  proof: { sha256: "...", diffLines: 12 },
});

chain.append({
  action: "publish",
  target: "v1.2.3",
  proof: { verdict: "PASS" },
});

const result = chain.verify();
// { valid: true, totalReceipts: 3 }

chain.save(".lux/receipts/2026-06-17.jsonl");
```

## Quick Start — Python

```python
from pathlib import Path
from popdd import HmacSigner, ReceiptChain

signer = HmacSigner(HmacSigner.load_or_create_key("./.lux/keys/agent.pem"))
chain = ReceiptChain(signer, agent_id="my-agent")

chain.append("verify", "calculateDiscount",
              {"verdict": "PASS", "passedClauses": 10000})
chain.append("edit", "src/pricing.py",
              {"sha256": "...", "diffLines": 12})
chain.append("publish", "v1.2.3", {"verdict": "PASS"})

result = chain.verify()
assert result.valid
chain.save("./.lux/receipts/2026-06-17.jsonl")
```

## Integration Patterns

### With SpecVerifier (mathematical proof → cryptographic chain)

```typescript
import { SpecVerifier, type FunctionSpec } from "lux-engine";

const verifier = new SpecVerifier();
const result = verifier.verify(spec, implementation, 1000);

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
```

### With Dafny (mechanized proof → cryptographic chain)

```typescript
import { dafnyVerify } from "lux-engine";

const result = dafnyVerify(SOME_DAFNY_METHOD);

chain.append({
  action: "dafny-prove",
  target: "CalculateDiscount",
  proof: {
    verdict: result.verdict,
    conditionsPassed: result.conditionsPassed,
    conditionsChecked: result.conditionsChecked,
  },
});
```

### As a test-runner wrapper (sign every test run)

```python
# scripts/popdd_verify.py — see templates/popdd-test-runner.py
import subprocess
from pathlib import Path
from popdd import HmacSigner, ReceiptChain

signer = HmacSigner(HmacSigner.load_or_create_key("./.lux/keys/agent.pem"))
chain = ReceiptChain(signer, agent_id="my-pipeline")
chain.append("test-run:start", "my-project", {"verdict": "STARTED"})

result = subprocess.run(["npx", "vitest", "run"], capture_output=True, text=True)
verdict = "PASS" if result.returncode == 0 else "FAIL"

chain.append("test-run:complete", "my-project", {
  "verdict": verdict, "exitCode": result.returncode
})
chain.save(Path("./.lux/receipts") / f"test-{Path.cwd().name}.jsonl")
```

### As a Hermes Agent extension

Wire into a Hermes skill so every tool call automatically produces a receipt. Pattern: after every tool call, append to the chain with the tool name and result. (This is the next step after the manual `chain.append()` pattern — not yet built.)

## Swapping the Signer (Ed25519, RSA, etc.)

The `Signer` interface is pluggable:

**TypeScript:**
```typescript
import { ed25519 } from "@noble/curves/ed25519";

class Ed25519Signer implements Signer {
  constructor(private privateKey: Uint8Array, public publicKey: Uint8Array) {}
  sign(data: Buffer | string): string {
    const buf = typeof data === "string" ? Buffer.from(data) : data;
    return Buffer.from(ed25519.sign(buf, this.privateKey)).toString("hex");
  }
  verifierId(): string {
    return Buffer.from(this.publicKey).toString("hex").slice(0, 16);
  }
}
```

**Python:**
```python
from typing import Protocol

class Signer(Protocol):
    def sign(self, data: bytes | str) -> str: ...
    def verifier_id(self) -> str: ...
```

Implement with Ed25519 using `cryptography` or `pynacl` for multi-party audit.

## Security Properties

| Property | How it's enforced |
|---|---|
| **Tamper detection** | Each receipt's signature covers its contentHash. Modifying any field → signature breaks. |
| **Order preservation** | Each receipt's previousHash = the prior receipt's contentHash. Reordering breaks the chain. |
| **Origin authentication** | The signer key is unique per agent. verifierId()/verifier_id exposes a key fingerprint for audit. |
| **Forward secrecy** (optional) | Rotate keys periodically; old chains remain verifiable if the old key is archived. |
| **Local-only signing** | Keys never leave the host. No remote signing service = no network attack surface. |

## End-to-End Pattern (The Real Demo)

The `demo/popdd-e2e.ts` file in LUX is a working, runnable end-to-end demonstration. It takes a real feature (`weightedAverage(prices, weights)`) through the full loop: spec → verify → sign 4 receipts → save → reload → tamper. Run it with:

```bash
npx tsx demo/popdd-e2e.ts
```

Use this as the template for any new feature POPDD run. The standard 4-step receipt pattern:

```typescript
chain.append({ action: "spec-write", target: "fnName", proof: { verdict: "PASS", preconditions: N, postconditions: N, invariants: N, edgeCases: N } });
chain.append({ action: "verify",      target: "fnName", proof: { verdict: result.verdict, passedClauses, totalClauses, invariantSamples } });
chain.append({ action: "edit",        target: "src/path.ts", proof: { verdict: "PASS", sha256, diffLines, added } });
chain.append({ action: "test-run",    target: "tests/path.test.ts", proof: { verdict: "PASS", tests, passed, failed, duration_ms } });
```

## Pre-Conditions Must Be Baseline-Input Safe (Critical Gotcha)

The LUX `SpecVerifier` explicitly tests every precondition against `undefined`, `null`, and `{}` BEFORE running it on real inputs. **Any precondition that throws on those values will fail the spec**, even if it's correct on real inputs.

**Wrong** (throws on `undefined`):
```typescript
check: ([prices, weights]) => prices.length === weights.length
```

**Right** (returns `false` gracefully):
```typescript
check: (i) => Array.isArray(i?.[0]) && Array.isArray(i?.[1]) && i[0].length === i[1].length
```

Rule of thumb: **if your spec check uses destructuring, optional chaining, or array methods, you will fail the baseline test**. Guard with `Array.isArray()` and early-return `false` for any invalid shape. This applies to preconditions AND postconditions.

**Use `lintSpec(spec)` from `lux-engine` to catch this BEFORE running the verifier** — it statically checks every clause with the same baseline inputs. The spec linter lives at `~/Documents/code/lux/src/proof/spec-linter.ts` (5 tests). Always lint before verifying.

This was the actual first-run bug in the weightedAverage e2e demo: 4/3011 clauses failed on baseline inputs, fixed in-session by hardening with `Array.isArray(i?.[N])` guards.

## Anti-Patterns

- **DON'T** use this as a replacement for proper access control. Receipts prove *what happened*, not *what was allowed*.
- **DON'T** sign plaintext secrets. The proof payload is signed, not the secrets themselves.
- **DON'T** trust the chain if you don't trust the signing key. Key compromise = chain forgery possible.
- **DON'T** use HMAC for multi-party audit. Switch to Ed25519 + public key broadcast for that.
- **DON'T** wrap a curried function like `weightedAverage(prices, weights)` in a spec as `{prices, weights}` object — the verifier passes a single value, not a curried arg list. Either pass a tuple `[prices, weights]` and destructure, or restructure as `weightedAverage({prices, weights})`.
- **DON'T** "introduce POPDD" by manually copying the receipt module into every project. **Use the packages** (`popdd`, `lux-popdd`) — that's the whole point of having packages. Manual copying is friction that defeats the goal.
- **DON'T** build a Python wrapper for a TypeScript project just to call POPDD. Either run the wrapper from the project that has a Python venv, or add a `requirements-dev.txt` to the TypeScript project, or skip the Python wrapper entirely (POPDD's TypeScript side covers the test-runner case).
- **DON'T** port the PDD toolchain to every language. Port only the receipt chain (`HmacSigner` + `ReceiptChain`). Spec format and verification stay language-native.

## Pitfalls (Real Bugs Hit in Production)

### 1. `chain.save()` — not `chain.save_to_jsonl()`

The Python API method is `ReceiptChain.save(path)`. There is no `save_to_jsonl`. Loading is `load_chain_from_jsonl(path)`. Mixing them up will cost you an `AttributeError` and a 5-minute detour. (Confirmed in 2026-06-17 — the very first version of `scripts/popdd_verify.py` used `save_to_jsonl` based on a hallucination.)

### 2. `DecisionReceipt` is a dataclass, not a dict

When reading a receipt back from a chain, **use attribute access**, not subscripting:

```python
# ✅ Correct
r = chain[0]
print(r.sequence, r.action, r.proof.get("verdict"))

# ❌ Wrong — TypeError: 'DecisionReceipt' object is not subscriptable
print(r["sequence"])
```

Attributes: `sequence`, `action`, `target`, `proof` (dict), `agent_id`, `verifier_id`, `previous_hash`, `content_hash`, `signature`, `timestamp`. Note the snake_case (not camelCase): `content_hash` not `contentHash`.

### 3. `sys.path.insert` for sibling packages — count the parents

When a script lives at `<project>/scripts/popdd_verify.py` and the popdd-py package is a **sibling repo** at `<parent>/popdd-py/`:

```python
# ✅ Correct (3 levels up: scripts → project → parent)
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "popdd-py"))

# ❌ Wrong (2 levels up — only reaches the project root, doesn't find popdd-py)
sys.path.insert(0, str(Path(__file__).parent.parent))
```

The "magic `/ ..`" pattern (`parent.parent / ".."`) is a no-op; `Path.__truediv__` doesn't normalize. Count the `parent.parent...` chain explicitly. The template at `templates/popdd-test-runner.py` shows the working version.

### 4. `parse_vitest_output` / `parse_pytest_output` is fragile

The `re.search(r"(\d+)\s+passed", output)` pattern misses some summary formats. Test with the actual output of your test runner before relying on the count. Two fallbacks:
- Parse the JSON output that most runners can produce (`pytest --json-report`, `vitest --reporter=json`).
- Just use `result.returncode == 0` for the verdict and drop the count if it's not critical to the audit trail.

### 5. `gh repo create --source=~/path` does NOT expand `~`

`gh` treats `--source=~/...` as a literal directory name. Use one of:

```bash
# Best: cd into the directory and use --source=.
cd ~/Documents/code/popdd-ts && gh repo create popdd-ts --public --source=. --push

# Or: absolute path (works because no ~)
gh repo create popdd-ts --public --source=/Users/chidionyema/Documents/code/popdd-ts --push
```

### 6. Verify `git init` actually created `.git/`

If you `git init` inside a directory that has a parent already under git, your commits may go to the parent's repository (or fail silently with `not a git repository`). Always verify after `git init`:

```bash
git init -b main && ls .git/HEAD   # MUST exist — if not, your init failed
```

(Confirmed in 2026-06-17: I committed twice before noticing the first commit had gone nowhere because no `.git/` was created in the target directory.)

### 7. Lint specs BEFORE running the verifier

`SpecVerifier` runs every precondition against `undefined`, `null`, `{}` first. If your check throws on those, the whole spec fails. Call `lintSpec(spec)` from `lux-engine` before `verifier.verify(spec, ...)` to catch the bug statically. Lives at `~/Documents/code/lux/src/proof/spec-linter.ts` (5 tests, exported from the package).

## Files

| File / Package | Purpose |
|---|---|
| `~/Documents/code/popdd-ts/` | `@lux/popdd` TypeScript package (zero deps). Public: https://github.com/chidionyema/popdd-ts |
| `~/Documents/code/popdd-py/` | `lux-popdd` Python package (zero deps). Public: https://github.com/chidionyema/lux-popdd |
| `~/Documents/code/lux/src/proof/receipt.ts` | LUX-side re-export shim (delegates to `@lux/popdd`) |
| `~/Documents/code/lux/src/proof/spec-linter.ts` | Catches the baseline-input trap before verifier runs |
| `~/Documents/code/lux/demo/popdd-e2e.ts` | Working end-to-end demo (weightedAverage feature) |
| `~/Documents/code/lux/tests/receipt.test.ts` | 20 tests — chain integrity, tamper detection, persistence |
| `~/Documents/code/lux/tests/popdd-e2e.test.ts` | 3 tests wrapping the demo as a CI gate |
| `templates/popdd-test-runner.py` | Drop-in Python test-runner wrapper that signs every run |

## Verified End-to-End Runs (2026-06-17)

Three real projects produce real signed chains as part of their workflow. Each chain is on disk, signed with the project's HMAC key at `<project>/.lux/keys/agent.pem` (0600 perms), and verifiable with `load_chain_from_jsonl(...)`:

| Project | `scripts/popdd_verify.py` signs | Verified result | Chain path |
|---|---|---|---|
| LUX | `npx vitest run` | **81 passed, 0 failed** | `~/Documents/code/lux/.lux/receipts/lux-test-<pid>.jsonl` |
| Prospector | `pytest -q --tb=no` (full suite) | **359 passed, 0 failed** | `~/Documents/code/prospector/.lux/receipts/prospector-test-<exitcode>.jsonl` |
| Signal Engine | `pytest <10 critical files>` | **69 passed, 0 failed** (after parser fix) | `~/Documents/code/signalengine/.lux/receipts/signalengine-test-<exitcode>.jsonl` |

**This is the proof that POPDD is a working product, not a demo.** Three independent projects, three different languages/test runners, same HMAC chain format, same `verify()` semantics. Each chain is independently verifiable: `from popdd import HmacSigner, load_chain_from_jsonl` (Python) or `import { HmacSigner, loadChainFromJsonl } from "@lux/popdd"` (TypeScript).

The Signal Engine parser fix (pitfall #4) is the worked example for "disclose-then-defer is wrong, fix first": the original `passed=0, failed=0` was a false attestation regardless of chain validity. Fix was 5 minutes; POPDD value depends on real numbers in the proof payload.

## Related Skills

- `lux-proof-driven-development` — The mathematical proof engine that POPDD chains results from
- `references/pdd-vs-popdd.md` — In the parent skill's references: a flat comparison table showing when to use each layer
- `task-resilience` — Persistence pattern (saving state every tool call); complements POPDD's audit-trail pattern
- `references/popdd-marketing-checklist.md` — How to honestly claim POPDD in public writing
