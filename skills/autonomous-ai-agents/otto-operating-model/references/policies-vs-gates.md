# Policies vs. Gates — The Two-Layer Enforcement Model

A lesson learned the hard way: **policies alone are files, not enforcement.**

## The Failure Pattern

1. User corrects a behaviour → I write a policy JSON → policy sits in `~/.hermes/policies/`
2. Next turn: I repeat the same behaviour → the policy file never fired
3. User corrects again → I write ANOTHER policy — still no runtime effect
4. Repeat until user demands a structural fix

**Root cause:** A JSON file in a directory is not a guard. Nothing reads policies at runtime unless a runtime enforcer is also deployed. The policy is **documentation** of what the guard should do — not the guard itself.

## The Two-Layer Model

### Layer 1: Policy (documentation)
File: `~/.hermes/policies/<id>.json`
What: Records what went wrong, what to do instead, confidence level, hit count
Purpose: **Observability and recall** — so the next agent session knows what was learned

### Layer 2: Gate (enforcement)
File: `~/.hermes/scripts/policy-enforcer.py`
What: Scans my action text against known violation patterns BEFORE I act
Purpose: **Runtime interception** — blocks the behaviour before it reaches the user

### How they connect

```
Correction happens
    ↓
1. Intent: encode what was learned
   → write policy JSON (the "what")
   ↓
2. Implement: wire up enforcement
   → add pattern to policy-enforcer.py (the "how")
   → OR: add a structural guard (dispatch gate, pre-commit hook, cron monitor)
   ↓
3. Verify: confirm the gate fires
   → run the enforcer against the offending action text
   → check policy-firings.jsonl
   ↓
4. Reflect: append to daily reflection
   → run reflect-on-correction.py
```

### When to escalate from policy to gate

| Trigger | Fix level |
|---------|-----------|
| First occurrence | Write policy only (confidence 0.3) |
| Second occurrence (same pattern) | Promote policy to active, add pattern to enforcer |
| Third occurrence (same pattern) | Structural fix: dispatch gate rule, cron monitor, pre-commit hook |
| Regress after structural fix | Re-audit the structural fix — did it actually work? |

### Case study: blocking subagent pattern (3+ violations → structural guard)

This pattern was corrected 3+ times across multiple sessions:
- **Correction 1:** "Subagent working — queued" blocks the chat. Policy written.
- **Correction 2:** Same pattern again. Policy promoted, dispatch-gate rule added.
- **Correction 3:** Same pattern during approval-gate-removal session. User: "how many times are we going to claim to have fixed this? I need proof not claims."
- **Structural fix:** `dispatch-guard.py` created at `~/.hermes/scripts/dispatch-guard.py`. A standalone CLI tool that blocks any `delegate_task` call without `background=True`. Must be invoked before every delegate_task call.

**Lesson: Patterns that repeat 3+ times need a tool-level guard, not another policy or skill instruction.** The guard must be something the agent invokes at the start of its response, not something it "remembers" to do.

### The Dispatch Gate Pattern

The most effective structural fix for permission-asking behaviour:
- `dispatch_gate.py` checks action text BEFORE every `clarify()` call
- If the text matches a permission-asking pattern → BLOCKED, execute instead
- This is a **pre-commit hook on my own output** — not something I have to "remember" to do

### Current enforcement mappings

| Policy | Enforced by | Status | Chain role |
|--------|-------------|--------|------------|
| pol-001 (kill without replacement) | policy-enforcer.py pattern `killed?.*process` | Active | Standalone |
| pol-002 (blocking sync task) | dispatch-gate rule + policy-enforcer.py | Active/Provisional | **Tier 1**: any long task >30s → background |
| pol-003 (options not action) | dispatch_gate.py + policy-enforcer.py | Active/Provisional | **Tier 1**: approach clear from spec → execute |
| pol-004 (no post-correction reflection) | reflect-on-correction.py (script) | Active | Standalone |
| pol-005 (surface vs act) | dispatch_gate.py | Active | Standalone |
| pol-006 (guessing API sigs) | policy-enforcer.py patterns `IIUC`, `I think` | Provisional | Standalone — unique domain (engineering/research) |
| pol-007 (permission-asking) | dispatch_gate.py patterns | Active | **Tier 2**: work scoped + safe → execute, don't ask |
| pol-008 (repeat after correction) | policy-enforcer.py + escalate-to-gate rule | Active | **Tier 3**: if corrected 2+ times, gate before clarify |
| pol-010 (verify instead of ask) | policy-enforcer.py | Active | Standalone — unique domain (engineering/verification) |
| pol-012 (test/build to subagents) | policy-enforcer.py + dispatch-guard.py | Active | **Tier 2**: never delegate test/build — bg processes only |

**Chain relationships:**
- infra/dispatch: pol-002 (T1, general long-task rule) → pol-012 (T2, specific test/build rule)
- decision-making: pol-003 (T1, options-not-action) → pol-007 (T2, ask-permission) → pol-008 (T3, repeat-gate)

Policies in a chain are expected to coexist. T1 is softer, T2 is sharper, T3 is structural. They should NOT be merged or archived just because they share a domain. Only pol-009 was archived (garbled auto-detection noise: "Deploy completes without errors. Failure type: LOGIC.").

**Note on archival discipline (corrected 2026-06-18):** Never archive a policy based on metadata alone (domain, hit count, confidence). Always read the `rule` and `trigger` fields and compare trigger conditions, not just domain labels. Two policies in the same domain may have COMPLETELY different triggers (e.g., pol-002 "any long task >30s → bg" vs pol-012 "test/build work never to subagents"). See `software-development/estate-management` skill for the full policy review methodology.
