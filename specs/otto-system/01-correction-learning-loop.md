# Build Note 01 — Correction-Learning Loop

*Part of the Otto system. See 00-MASTER.md for the architectural context.*

## What it is

A bounded, auditable loop that converts every user correction into a structured policy, enforces it at decision time, and measures its effectiveness over time.

## Key Files

| File | Purpose |
|------|---------|
| `~/.hermes/scripts/otto-learn.py` | CLI: add/list/fire/review policies |
| `~/.hermes/scripts/policy-enforcer.py` | Runtime guard — blocks action patterns matching active policies |
| `~/.hermes/scripts/reflect-on-correction.py` | Post-correction hook — appends analysis to daily reflection |
| `~/.hermes/policies/pol-*.json` | Policy store (8 active as of 2026-06-18) |
| `~/.hermes/policies/archived/` | Retired policies |
| `~/.hermes/logs/policy-firings.jsonl` | Every policy fire event |
| `~/.hermes/logs/reflection/YYYY-MM-DD.md` | Daily reflection with correction analysis |

## Design

### Policy lifecycle

```
provisional (confidence 0.3)  →  active (confidence >= 0.8)  →  retired
         ↓ hits >= 3 and helped > hurt    ↓ helped/hurt < 0.4
```

- **Provisional:** Written on correction, narrow scope, does not inject into strategic dispatches
- **Active:** Promoted when proven useful (3+ hits, more helped than hurt). Injects into context via memory_retrieval.py
- **Retired:** Moved to archive when hurtful or no longer relevant

### Runtime enforcement

`policy-enforcer.py` is called before every `clarify()` or `delegate_task()` call. It:
1. Scans the action text against 18 regex patterns mapped to 8 policies
2. If a pattern matches → fires the policy to the firing log, prints BLOCKED with the rule to apply instead
3. If no pattern matches → prints PASS, action proceeds

### Post-correction protocol

When the user corrects Otto:
1. `python3 ~/.hermes/scripts/reflect-on-correction.py` — appends analysis to daily reflection
2. Promote the triggered policy to active (set status=active, confidence=0.8)
3. Check all other policies for promotion/demotion candidates
4. If this correction repeats a previous one → structural fix (new gate/enforcer), not another policy

### Structural fix rule

"If this correction is the same pattern as a previous correction, the fix must be a structural change (runtime hook, gate, pre-commit check), not another policy. Policies alone are not enforcement — they are documentation of enforcement that must also exist."

### Convergence

- Each correction adds <= 1 policy
- Each idle run may remove <= N policies (retirement)
- The evaluator (reflect-on-correction.py) is a static script, never self-modified
- The enforcer (policy-enforcer.py) is human-audited via git
- Net policy count cannot grow unbounded because dead policies are retired
