# Policy Review Methodology

This reference captures the structured framework for evaluating dead/dormant policies.
**Revised 2026-06-18** — After a correction where loose supersedence logic caused valid policies to be archived prematurely.

## First Rule: READ THE RULE TEXT

Never make an archival decision based on metadata alone (domain, hit count, confidence). 
Open the JSON file, read the `rule` and `trigger` fields, and compare trigger conditions,
not just domain labels.

**Why:** Two policies in the same domain may have completely different triggers.
`pol-002` (infra/dispatch, "use bg=true for any long task") and `pol-012` (infra/dispatch,
"never delegate test/build to subagents") look like duplicates by metadata but are 
different: one is a general dispatch rule, the other is a specific technical restriction.

## Decision Framework for Dead/Dormant Policies

When reviewing policies with 0 hits, apply these checks **in order**. Stop at the first
definitive answer.

### 1. Is This Part of an Escalation Chain?

Check for `escalates_to`, `supersedes`, `depends_on`, or `superseded_by` fields.

A policy that is part of a tiered chain (e.g., Tier 1: general rule, Tier 2: sharper 
rule, Tier 3: structural gate) is expected to have 0 hits — it only fires when the
tier below it fails. **Do not archive chain members.**

**Example:** The decision-making chain has 3 tiers:
- Tier 1 (pol-003): "execute when priority is clear from spec" — provisional, 0 hits
- Tier 2 (pol-007): "execute when work is scoped and safe (money/identity/moat guard)" — active, 1 hit
- Tier 3 (pol-008): "gate via dispatch_gate.py if pattern repeats 2+ times" — active, 1 hit

Tier 1 has 0 hits because the user hasn't explicitly complained about "options presented"
since it was created. It's still valid. Keep it.

### 2. Supersedence Check

Does an active policy exist in the same domain with a **sharper rule, higher confidence, 
and overlapping trigger conditions**? 

**CRITICAL:** The trigger conditions must overlap, not just the domain. 
"Same domain, higher confidence" is NOT enough for supersedence.

- If triggers overlap → supersedence likely. The newer policy covers the scenario.
- If triggers are distinct → NOT supersedence, even if same domain.

**WRONG example (from production):** Archived pol-002 because pol-012 existed in the
same domain with higher confidence. Both rules were valid — one general, one specific.
They form an escalation chain, not a supersedence.

**RIGHT example:** pol-003 (decision-making, "don't present options") and pol-007 
(decision-making, "don't ask permission") have overlapping triggers (both fire when
the agent is about to seek input instead of executing). But they're kept as an
escalation chain because pol-003 is a softer version that fires first, and pol-007
is a sharper version for when the softer rule doesn't work.

### 3. Domain Coverage Check

Does this policy's domain have **any** active policies? If not, archiving it leaves a
blind spot. Keep it and improve the rule rather than losing domain coverage entirely.

**Example:** `engineering/research` had only one policy (pol-006, "read source code
before guessing API signatures"). Archiving it would mean this domain has zero 
policies — any future "guess instead of reading source" error would have no guard.

### 4. Rule Coherence Check

Read the rule text and trigger conditions. Is the rule:
- Actionable? (Can the agent actually act on it?)
- Coherent? (Does the rule text form a complete sentence?)
- Non-contradictory? (Does the action match the trigger?)

**Archive if garbled.** Example: pol-009 (engineering/reliability) had rule text:
"Deploy completes without errors. Failure type: LOGIC." — reads like corrupted 
auto-detection output from the outcome evaluator. Confidence 0.3, zero hits. 
Cannot be salvaged without original intent.

### 5. Confidence Check

Policies created with:
- `confidence < 0.5` AND `hits = 0` AND `age >= 7 days` → archive candidate
- `confidence >= 0.7` AND `source_correction` mentions a real incident → keep, give runway
- `confidence >= 0.5` AND unique domain → keep

Confidence alone is not decisive, but low confidence + zero hits + garbled text is
a strong archive signal.

## Overlap vs Escalation Chain

This is the subtlest judgment in policy review. The distinction:

| Criterion | Overlap (merge) | Escalation Chain (keep separate) |
|---|---|---|
| Same trigger? | Yes — they fire in the same context | No — each has a distinct trigger condition |
| Different severity? | No — same severity, same rule | Yes — tier 1 is softer, tier N is tighter |
| Can coexist? | Wasteful — one covers it | Intentional — they form a progression |
| Example | Two policies that both fire on "non-zero exit" | 003 says "don't present options", 007 says "don't ask", 008 says "gate before asking" |

When in doubt, keep separate and add chain metadata. Merging loses coverage;
keeping separate costs only a few bytes of JSON and one more slot in retrieval.

## Policy Chain Metadata Fields

Each policy JSON supports these chain-relationship fields. Use them to make
architectural intent explicit:

```json
{
  "depends_on": ["pol-20260618-003"],    // Tier 1 — this policy is downstream
  "supersedes": "pol-20260618-003",      // Tier 2 — this policy replaces tier 1 when it fires
  "superseded_by": null,                 // If set, this policy has been replaced
  "escalates_to": "pol-20260618-012",    // Tier 1 — if this fails, escalate to tier 2
  "notes": "Tier 2/3 in decision-making chain. Active with 1 hit..."
}
```

Fields are optional. A policy in a chain only needs `escalates_to` or `depends_on` —
the detector checks for any of them to skip archival consideration.

## Common Archival Pitfalls

- **Don't archive policies that are part of an escalation chain.** They have 0 hits by design.
- **Don't archive young policies.** Use a 7-day grace period. Policies created today haven't had opportunities to fire yet. (But do NOT extend this to chain members — their 0-hit state is permanent by architecture, not by age.)
- **Don't archive policies from unique domains.** Even if they're weak, they cover territory no other policy does. Keep and improve the rule.
- **Don't confuse "same domain" with "same trigger."** Two infra/dispatch policies can coexist with completely different triggers.
- **Don't leave duplicate archive directories.** Consolidate to `policies/archived/` — check for both `archived/` and `_archived/` on any policy move.
- **Always read the JSON.** Metadata in the estate inventory screen (hit count, domain, status) is insufficient for an archive decision. The rule text and trigger conditions tell the real story.

## After Archiving

1. Update the estate inventory (run `estate-inventory.py` or full pipeline)
2. Check for duplicate archive directories (`archived/` vs `_archived/`) — consolidate
3. Run drift detection to confirm the reduced policy count is reflected
4. Commit to git so history is preserved
