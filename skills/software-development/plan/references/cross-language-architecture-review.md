# Cross-Language Architecture Review Pattern

Captured 2026-06-17 after building PDD enforcement for Python/TS before checking for .NET projects.

## The Pattern

Before building ANY tool, package, or CLI that spans multiple languages:

1. **Identify all language ecosystems** in active projects — grep for `.py`, `.ts`, `.cs`, `.fs`, `.sln`, `Cargo.toml`, `go.mod`, etc.
2. **Define the language-agnostic contract first** — what format/schema/protocol do all languages share? (e.g. JSONL receipts, not Python dataclasses or TS interfaces)
3. **Build the CI gate (language-agnostic) before the language-specific tools** — one shell script that reads the shared format is worth more than three per-language CLIs.
4. **Only then build language-specific implementations** — once the contract is stable.

## Why

Duplicating `lux spec` into Python, .NET, and Go is a trap. The receipt format (JSONL written to `.lux/receipts/`) is the bridge. Build that first, then each language just needs a signing library — not a full CLI.

## Worked Example (from 2026-06-17)

**Context:** I built `lux spec` CLI (TypeScript), `popdd_agent.py` (Python hot-chain), and started drafting `dotnet-popdd` before checking what languages the user actually had. They had .NET solutions — `haworks.sln`, `StorePlatform.sln`, `TheIntroductionExchange.sln` — that were never considered.

**What should have happened:**

```
1. Identify: Python, TypeScript, .NET (C#/F#)
2. Define contract: JSONL receipt format (already exists in popdd-ts/lux-popdd)
3. Build CI gate: one shell script that reads receipts, checks coverage
4. Build per-language: just signing libraries (TS done, Python done, .NET needs NuGet package)
```

**What actually happened:**
```
1. Built `lux spec` CLI (TypeScript-only)
2. Deployed `popdd_agent.py` (Python-only)
3. Started drafting dotnet-popdd
4. User: "what about .NET?"
```

The fix: design the language-agnostic contract (receipt JSONL → CI gate) before building any language-specific tool.

## When to Trigger

- Task asks you to "integrate X across all projects"
- You find yourself writing the same logic in a second language
- The user says "what about .NET / Rust / Go?"
- You're about to build a CLI tool — ask: is this one language, or should it be language-agnostic?

## Anti-Pattern

Build per-language then reconcile:
```
Python tool → TS tool → .NET tool → "Wait, these are all different formats"
```

## Correct Pattern

```
Shared contract (JSONL receipts) → CI gate (shell) → per-language signing libs
```
