# LUX Architecture — 4 Independent Layers (Decoupled)

**Last updated:** 2026-06-18  
**Reason for update:** This session decoupled all 4 layers from a single LUX repo into independent packages, each in its own repo with zero inter-dependency.

## The Dependency Graph (Current)

```
popdd (TypeScript)          lux-popdd (Python)
  ├── npm: (not yet)          ├── PyPI: (not yet)
  ├── GH: chidionyema/popdd-ts ├── GH: chidionyema/lux-popdd
  ├── 18 tests pass            ├── 21 tests pass
  └── zero deps                └── zero deps
       │                             │
       └──────────┬──────────────────┘
                  │ OPTIONAL INTEGRATION
                  ▼
lux-spec (Python)               lux-engine (TypeScript)
  ├── GH: (local only)             ├── GH: (not yet)
  ├── 53 tests pass                ├── 79/81 tests pass
  ├── zero deps                    ├── deps: popdd
  └── SpecVerifier,                └── semantic graph,
       VerifiedFunction,                type-level proofs,
       test generator,                   Dafny bridge,
       spec linter                        Semgrep audit
       │                         
       ▼
lux-spec-cli (Python)
  ├── GH: (local only)
  ├── 14/17 tests pass
  ├── degrades gracefully when deps missing
  ├── commands: init, spec create, spec verify, spec guard, spec check
  └── depends on: lux-spec (optional), lux-popdd (optional)
```

## Layer Definitions

| Layer | What it does | Verification level | Language | Package name |
|-------|-------------|-------------------|----------|-------------|
| **1. POPDD** | Cryptographic chain-of-custody. Signs JSON, detects tampering. | HMAC-SHA256 | TS + Py | `popdd` / `lux-popdd` |
| **2. Spec Engine** | Formal spec types + runtime verification. Pre/post/invariant/edge. | Statistical (sampling) | Py (TS also exists in lux-engine) | `lux-spec` |
| **3. Spec CLI** | CI gate. `init`, `spec create`, `spec verify`, `spec guard`, `spec check`. | Orchestration | Py | `lux-spec-cli` |
| **4. LUX Engine** | Full PDD platform. Semantic graph, type-level proofs, Dafny bridge. | Mechanical (type system) + Statistical | TS | `lux-engine` |

## Design Rules

### Rule 1: No dependencies between layers in the same project

POPDD (Layer 1) is installed in Signal Engine and Prospector WITHOUT LUX. It knows nothing about specs.

lux-spec (Layer 2) is installed in Signal Engine WITHOUT POPDD. It verifies without signing.

Only the CLI (Layer 3) or an explicit integration script combines them.

### Rule 2: The receipt IS the shared contract

Every language writes the same JSONL receipt format. The CI gate reads receipts — it doesn't care what language wrote them. This is the only cross-language contract.

### Rule 3: Spec format is language-agnostic JSON

```json
{
  "functionName": "validateEmail",
  "preconditions": [{"name": "...", "description": "...", "check": "..."}],
  "postconditions": [{"name": "...", "description": "...", "check": "..."}],
  "invariants": [{"name": "...", "description": "...", "check": "..."}],
  "edgeCases": [{"name": "...", "input": ..., "expectedOutput": ...}],
  "noThrow": false,
  "idempotent": false
}
```

The same JSON file works in TypeScript (lux-engine) and Python (lux-spec). The `check` functions are native code — JSON only stores metadata. The actual verification logic is always in the package's native language.

### Rule 4: Degrade gracefully

The CLI (`lux-spec-cli`) works without any optional dep installed:
- `lux-spec init` — works bare (just creates directories)
- `lux-spec spec create` — works bare (generates JSON stubs)
- `lux-spec spec verify` — structural check only if lux-spec missing; full verification if installed
- `lux-spec spec guard` — works bare (reads registry)
- POPDD signing — skipped if lux-popdd missing, active if installed

## What's Missing

| Gap | Impact | Fix |
|-----|--------|-----|
| `popdd` not on npm | Can't `npm install popdd` | `npm publish` in ~/Documents/code/popdd-ts (needs npm login) |
| `lux-popdd` not on PyPI | Can't `pip install lux-popdd` | `hatch publish` (needs PyPI token) |
| `lux-spec` not on PyPI | Can't `pip install lux-spec` | `hatch publish` (needs PyPI token) |
| `lux-spec-cli` not on PyPI | Can't `pip install lux-spec-cli` | `hatch publish` (needs PyPI token) |
| `lux-engine` not on GitHub or npm | No public repo for LUX | `gh repo create`, `npm publish` |
| `.NET` POPDD package | No NuGet for C# projects | Port `HmacSigner` + `ReceiptChain` |
| CI auto-publish | Manual publish only | GitHub Actions on tag push |

## Files on Disk

| Path | Layer | What |
|------|-------|------|
| `~/Documents/code/popdd-ts/` | 1 | `popdd` npm package source |
| `~/Documents/code/popdd-py/` | 1 | `lux-popdd` PyPI package source + `popdd.agent.PopddAgent` |
| `~/Documents/code/lux-spec-py/` | 2 | `lux-spec` PyPI package source |
| `~/Documents/code/lux-spec-cli/` | 3 | `lux-spec-cli` PyPI package source |
| `~/Documents/code/lux/` | 4 | `lux-engine` npm package source (not yet separate repo) |
| `~/Documents/code/signalengine/` | Consumer | Uses all 4 layers |
| `~/Documents/code/prospector/` | Consumer | Uses all 4 layers |
