# Cross-Language Architecture Review Pattern

## When to Use

When a design or tool needs to work across Python, TypeScript, .NET, and potentially other languages. Run this review BEFORE building language-specific implementations.

## The Pattern

### Step 1: Identify the Language-Agnostic Contract

What single format, protocol, or interface do ALL languages need to produce/consume?

For the PDD/POPDD stack, this is the **receipt JSONL**:
- Every language writes `{action, target, proof, contentHash, previousHash, signature}` to `.lux/receipts/<date>.jsonl`
- The CI gate reads ONLY this format — it doesn't care what language wrote it

### Step 2: Identify What Stays Language-Native

These are things that SHOULD be different per language:

| Concern | Language-native approach |
|---------|-------------------------|
| Spec format | TS: `FunctionSpec` types. Python: dataclasses. C#: attributes |
| Verifier | TS: `SpecVerifier`. Python: `hypothesis`. C#: `FsCheck` |
| Signing library | TS: `@lux/popdd`. Python: `lux-popdd`. C#: (needs `dotnet-popdd`) |

### Step 3: Build the Contract First

Build the shared format/schema before any language implementation. Then build one language implementation, test it against the contract, then the next.

**Do NOT build all language implementations simultaneously.** Build the contract, build one reference implementation (usually Python or TS), verify the contract works, then add the next language.

### Step 4: CI Gate Before Language Ports

The CI gate (one shell script, all languages) should be built BEFORE the second language implementation. This way:
- The gate validates the contract is complete enough
- You can test the second language against the gate immediately
- The gate doesn't get language-specific bias

## Worked Example: PDD/POPDD Cross-Language

### What Was Built (the wrong order)

1. ❌ LUX `lux spec` CLI (TypeScript-only) — built first
2. ❌ `popdd_agent.py` (Python) — built second, without .NET plan
3. ❌ Architecture review requested AFTER implementation — should have been first

### What the Order Should Have Been

1. ✅ Define the receipt JSONL schema (language-agnostic)
2. ✅ Build one reference signing library (Python `popdd` — zero deps, easy to iterate)
3. ✅ Build the CI gate (shell script that reads receipts, checks coverage)
4. ✅ Port signing to TypeScript (`@lux/popdd`)
5. ✅ (next) Port signing to .NET (`dotnet-popdd` NuGet)
6. ❌ NEVER port the entire PDD toolchain per language. Receipt chain only.

## Key Questions to Ask Before Building

- "Is the format/language/location of the shared contract defined?"
- "Does the CI gate work without knowing which language produced the receipts?"
- "Am I building a language-specific tool (fine) or am I assuming it becomes the cross-language standard (needs review)?"
- "Have I asked the user if there's a language I'm not considering?" (They have .NET projects — I didn't check before building.)
