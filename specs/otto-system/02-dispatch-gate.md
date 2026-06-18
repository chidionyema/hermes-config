# Build Note 02 — Dispatch Gate

*Part of the Otto system. See 00-MASTER.md for the architectural context.*

## What it is

A structural pre-commit gate that prevents Otto from asking the user for permission to do well-scoped work. Runs before every `clarify()` call. If the gate says `DISPATCH_NOW`, execute immediately — no question.

## Why it exists

Policies alone failed. The asking-permission pattern was corrected multiple times (policies 003, 007, 008) but kept repeating because the enforcement was "remember to check the policy" — a manual step. The gate is a hard-coded script that runs before every action, not a policy to remember.

## Implementation

**File:** `~/.hermes/scripts/dispatch_gate.py`

**Logic:**
1. Parse the proposed action text
2. Check against forbidden patterns (`"should I"`, `"want me to"`, `"shall I"`, etc.)
3. Return `DISPATCH_NOW` (execute) or `DISPATCH_NEEDS_USER` (only then ask)

## Enforcement

The SKILL.md correction protocol says: "If this correction is the same pattern as a previous correction, the fix must be a structural change (runtime hook, gate, pre-commit check), not another policy."
