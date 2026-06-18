# Policy Review Methodology

## Decision Framework for Dead/Dormant Policies

When reviewing policies with 0 hits, apply these checks in order:

### 1. Supersedence Check
Does an active policy exist in the same domain with a sharper rule, higher confidence, and overlapping scope?

Example: `pol-20260618-002` (infra/dispatch, "use background=true for long tasks") was superseded by `pol-20260618-012` (infra/dispatch, "never delegate test/build work — use background processes") — more specific, higher confidence (0.8), active status.

**Verdict if yes:** → Archive. The newer policy covers the scenario better.

### 2. Domain Coverage Check
Does this policy's domain have **any** active policies? If not, archiving it leaves a blind spot.

Example: `pol-20260618-006` (engineering/research, "read source code before guessing API signatures") had domain `engineering/research` with zero other policies.

**Verdict if no:** → Keep. The concept may be valid; it just needs more runway.

### 3. Rule Coherence Check
Read the rule text and trigger conditions. Is the rule actionable? Coherent? Non-contradictory?

Example: `pol-20260618-009` (engineering/reliability) had garbled rule text: "Deploy completes without errors. Failure type: LOGIC." — reads like corrupted auto-detection output. Confidence 0.3.

**Verdict if garbled:** → Archive. Cannot be salvaged without original intent.

### 4. Confidence Check
Policies created with confidence < 0.5 and 0 hits after 7+ days are low-value candidates.

Policies created with confidence >= 0.7 and from correction corpus entries should be given more runway.

### 5. Overlap Consolidation Check
When 2+ policies exist in the same domain, check if they:
- Fire in the same contexts (co-firing)
- Have overlapping but not identical rules
- Could be merged into a single policy with conditional sub-rules

Example: `decision-making` domain had pol-007 ("execute without asking") and pol-003 ("dispatch instead of presenting options") — same intent, different verbosity. pol-007 was kept, pol-003 archived.

**Overlap does not always mean merge.** Two policies in the same domain with distinct triggers can coexist (e.g., one fires on CLI output, one on file-watch events).

## Common Archival Pitfalls

- **Don't archive young policies.** Use a 7-day grace period. Policies created today haven't had opportunities to fire yet.
- **Don't archive policies from unique domains.** Even if they're weak, they cover territory no other policy does. Keep and improve the rule.
- **Don't leave duplicate archive directories.** Consolidate to `policies/archived/` — check for both `archived/` and `_archived/` on any policy move.
- **Always log the action.** Every archive/consolidation should write to `logs/remediation/actions.jsonl` with `dry_run: true/false`.

## After Archiving

1. Update the estate inventory (run `estate-inventory.py` or full pipeline)
2. Delete the `_archived/` directory if it became a duplicate after consolidation
3. Run drift detection to confirm: new snapshot should show reduced policy count
4. Commit the archival to git so history is preserved
