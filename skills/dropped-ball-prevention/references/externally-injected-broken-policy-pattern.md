# Externally-Injected Broken-Policy Pattern (added 2026-08-16)

## What this is

The 2026-08-08 fix added a **3-gate** broken-policy defense to `near-miss-analyzer.py`:
1. `rule_quality()` check in `idle-consolidation.py` before promotion
2. Skeleton-dedup gate in `near-miss-analyzer.py:auto_create_policies` (line 163-211)
3. Write-gate collision check against `archived/` (line 219, 237-249)

Gate 2026-08-15 audit verified all 3 gates blocked resurrection of the original `pol-auto-fix-coordinator` family (0 post-demotion firings). The 2026-08-16 audit found that **a new broken-policy family bypassed gates 2 and 3 entirely**: `pol-shadow-gap-2026MMDD-HHMMSS-{automation,api_usage,...}.json`.

## Why the gates didn't catch it

The skeleton-dedup gate (gate 2) only runs against the **auto-created** `pol-auto-{domain}-{date}` template:
```python
rule_text = f"Handle {domain} issues proactively. If a failure in {domain} occurs, create a structured policy entry."
skel = _skeleton(rule_text)
if _policy_skeleton_in_use(skel, hermes_home):
    skipped_skeleton += 1
```

The skeleton is computed from the auto-created rule template, NOT from the rule templates of **existing policies in `policies/`**. Externally-injected policies (created by subagent calls, strategist dispatches, or `otto-learn add` from outside the auto-creation path) bypass this gate because:
- Their id pattern (`pol-shadow-gap-...`) doesn't collide with the auto-created `pol-auto-{domain}-{date}` naming
- The id collision check (gate 3) is on the proposed new pid vs archived filenames — never compares rule skeleton
- The near-miss-analyzer never iterates over `policies/` and asks "are these existing files broken?"

## Symptom (in `~/.hermes/logs/maintenance/<date>.md`)

The near-duplicate detector surfaces 25+ similarity-1.00 pairs among policies with **identical rule text** but different ids (different timestamps in the id):
```
(1.00) pol-shadow-gap-20260815-070052-automation ↔ pol-shadow-gap-20260815-080000-automation
  A: [SHADOW] Detected gap in automation: You keep hitting 'autom
  B: [SHADOW] Detected gap in automation: You keep hitting 'autom
```

## Diagnostic (count the family + verify zero firings)

```bash
ls ~/.hermes/policies/pol-shadow-gap-*.json 2>/dev/null | wc -l
grep -c "pol-shadow-gap-" ~/.hermes/logs/policy-firings.jsonl 2>/dev/null
# Both calls together: 28 files, 0 firings = Class C externally-injected broken-policy family
```

## Fix recipe (executed 2026-08-16)

When you find this pattern:

1. **Archive all members** in a single loop:
   ```bash
   for f in ~/.hermes/policies/pol-shadow-gap-*.json; do
     python3 -c "
   import json, os
   src = '$f'
   dst = os.path.expanduser('~/.hermes/policies/archived/' + os.path.basename(src))
   with open(src) as fh: d = json.load(fh)
   d['status'] = 'archived'
   d['archived_at'] = '<UTC-ISO>'
   d['archived_by'] = 'strategist-audit-YYYY-MM-DD'
   d['archive_reason'] = 'Class C externally-injected broken-policy: shadow-gap family, 0 firings, identical skeleton'
   with open(dst, 'w') as fh: json.dump(d, fh, indent=2)
   os.remove(src)
   "
   done
   ```
   **Pitfall:** the Python f-string `dst = "~/.hermes/..."` does NOT expand `~`. Use `os.path.expanduser()` or pass the absolute path via shell variable. First attempt at this fix failed because Python's heredoc didn't see the shell tilde expansion.

2. **Patch the gate** (deferred to Claude operator-shell lane — `near-miss-analyzer.py` is in the script-write lane):
   - Add a fourth gate: **before auto-creating** any policy, also compute skeleton of existing `policies/*.json` (not just the proposed rule) and skip if a near-duplicate exists.
   - The current gate dedups **the new policy against existing skeletons**. The missing gate dedups **across the family of existing policies themselves** — but that's a "consolidation pass" concern, not an "auto-create" concern.
   - **Real fix:** `idle-consolidation.py` should detect externally-injected families with identical skeletons and demote them, not rely on the near-miss auto-creation path to dedup.

3. **Verify the family is gone from active policies/ but present in archived/**:
   ```bash
   find ~/.hermes/policies -maxdepth 1 -name "pol-shadow-gap-*.json"  # expect 0
   ls ~/.hermes/policies/archived/pol-shadow-gap-*.json 2>/dev/null | wc -l  # expect N
   ```

## What this skill does NOT cover

- The `pol-auto-fix-*` family (Class A/B) — already fully resolved 2026-08-08 with verified gates
- Genuinely new policies that share skeleton with retired ones (these are escalation chains, not duplicates — read the rule text + check `escalates_to`/`supersedes`/`depends_on` fields before archiving)
- Auto-templated entries in the self-regression corpus (`health-bridge/signalengine` "Would policy now prevent signalengine tests from failing unnoticed?") — these are corpus noise, separate concern

## Cross-reference

- SKILL §10 (three-class taxonomy of broken policies) in `autonomous-ai-agents/otto-operating-model` SKILL.md
- `references/byte-offset-cursor-dedup.md` — the byte-offset pattern for preventing duplicate appends in JSONL logs (different mechanism, same goal: stop duplicate data)
- `near-miss-analyzer.py:163-211` (skeleton function) and `:219,237-249` (write gate) in `~/.hermes/scripts/`
- `idle-consolidation.py:160` (rule_quality gate) in `~/.hermes/scripts/`