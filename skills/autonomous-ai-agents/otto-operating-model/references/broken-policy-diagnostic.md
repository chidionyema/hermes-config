# Broken-Policy Diagnostic & Auto-Execute Playbook

**Live evidence:** the daily-strategist-audit ran on 2026-08-08 against this exact failure mode. Verified three-class taxonomy of broken policies, all firing in production.

## Three classes of broken policy

| Class | Pattern | Detection | Action |
|---|---|---|---|
| **A — broken-rule** | Rule literally says "needs refinement" / "to be refined" / empty | `grep '"rule": "When .* needs refinement' ~/.hermes/policies/*.json` | Demote + patch promoter |
| **B — negative-evidence** | hurt/helped ratio > 0.3 with hits > 5 | `python3 broken-policy-check.py --class b` | Demote regardless of confidence |
| **C — auto-templated duplicates** | Multiple policies whose rules differ only by an embedded number/count | Group policies by rule-skeleton (strip digits/timestamps) and look for groups ≥ 3 | Demote all + patch near-miss analyzer to dedupe on skeleton |

## Diagnostic commands (run before any fix)

```bash
# Class A — broken-rule grep
grep -l '"rule": "When .* needs refinement' ~/.hermes/policies/*.json

# Class B — hurt/helped ratio per policy
cd ~/.hermes/policies && for f in *.json; do
  python3 -c "
import json, sys
try:
    p = json.load(open('$f'))
    h = p.get('hits', 0); hp = p.get('helped', 0); ht = p.get('hurt', 0)
    if h > 5 and ht > 0 and ht/(hp+ht) > 0.3:
        print(f'$f: hits={h} helped={hp} hurt={ht} ratio={ht/(hp+ht):.2f}')
except: pass
"
done

# Class C — auto-templated duplicates (rule-skeleton similarity)
python3 << 'EOF'
import json, os, re
from collections import defaultdict
skeletons = defaultdict(list)
for f in os.listdir('/Users/chidionyema/.hermes/policies'):
    if not f.endswith('.json'): continue
    p = json.load(open(f'/Users/chidionyema/.hermes/policies/{f}'))
    rule = p.get('rule','')
    # Strip digits and timestamps
    skeleton = re.sub(r'\d+', 'N', rule)
    skeleton = re.sub(r'\d{4}-\d{2}-\d{2}.*?(\d{2}:\d{2}:\d{2})?', 'TS', skeleton)
    skeletons[skeleton].append(f)
for s, files in skeletons.items():
    if len(files) >= 3:
        print(f'Skeleton with {len(files)} duplicates: {s[:80]}')
        for f in files: print(f'  {f}')
EOF

# Companion: how often is each broken policy firing?
for id in pol-auto-fix-coordinator pol-auto-fix-cron pol-auto-prospector-moat-20260802*; do
  count=$(grep -c "\"policy_id\": \"$id\"" ~/.hermes/logs/policy-firings.jsonl 2>/dev/null || echo 0)
  echo "$id: $count firings"
done
```

## Idle-consolidation patch (the actual gate fix)

Add a `rule_quality()` check to `promote_candidates()` in `~/.hermes/scripts/idle-consolidation.py` (currently lines 160-171):

```python
import re

BROKEN_RULE_RE = re.compile(r'(needs refinement|to be refined|\btbd\b|\bxxx\b)', re.IGNORECASE)

def rule_quality(p):
    rule = (p.get('rule') or '').strip()
    if not rule:
        return False, 'empty rule'
    if BROKEN_RULE_RE.search(rule):
        return False, 'rule text admits incompleteness'
    hurt = p.get('hurt', 0) or 0
    helped = p.get('helped', 0) or 0
    hits = p.get('hits', 0)
    if hits > 5 and hurt > helped and (hurt / (helped + hurt)) > 0.3:
        return False, f'negative-evidence ratio {hurt/(helped+hurt):.2f}'
    return True, 'ok'

def promote_candidates(policies):
    candidates = []
    for p in policies:
        if p.get('status') != 'provisional':
            continue
        ok, reason = rule_quality(p)
        if not ok:
            continue  # fence out silently — log to idle-consolidation.log
        hits = p.get('hits', 0)
        helped = p.get('helped', 0) or 0
        hurt = p.get('hurt', 0) or 0
        if hits >= PROMOTE_MIN_HITS and helped > hurt and helped >= PROMOTE_MIN_HELPED:
            candidates.append(p)
    return candidates
```

## Near-miss-analyzer patch (Class C prevention)

In `~/.hermes/scripts/near-miss-analyzer.py`, before auto-creating a new provisional policy, normalize the proposed rule and compare against existing policies' skeletons. If a skeleton match exists, log a "duplicate suppressed" entry to the JSONL instead of writing a new policy.

```python
import re
from difflib import SequenceMatcher

def rule_skeleton(rule: str) -> str:
    return re.sub(r'\d+', 'N', rule).strip()

# Before creating pol-auto-prospector-moat-NEW:
new_skel = rule_skeleton(proposed_rule)
for existing in glob.glob('~/.hermes/policies/pol-*.json'):
    if rule_skeleton(json.load(open(existing))['rule']) == new_skel:
        log('near-miss-suppressed', existing=existing, new_skel=new_skel)
        return  # skip creation
```

## Verification after fix

```bash
# Re-run the diagnostic
grep '"rule": "When .* needs refinement' ~/.hermes/policies/*.json
# Expected: 0 matches

# Re-run idle-learning once
~/.hermes/scripts/idle-learning-run.sh

# Confirm firings log stabilizes
ls -la ~/.hermes/logs/policy-firings.jsonl
# Should not grow by 4+/day anymore

# Confirm reflection stops duplicating
grep -c "Auto-Reflection" ~/.hermes/logs/reflection/$(date +%F).md
# Should return ≤1
```

## Audit-itself-can-silent-stretch (recursive failure mode)

When the daily-strategist-audit itself silently-stretches, the next audit must read its own prior `last_error` text from `cron/jobs.json` and fold that into the carry-over table instead of re-deriving everything. Diagnostic:

```bash
python3 -c "
import json
d = json.load(open('/Users/chidionyema/.hermes/cron/jobs.json'))['jobs']
a = [j for j in d if j.get('id') == '85385abb646d'][0]
print('last_run_at:', a.get('last_run_at'))
print('last_status:', a.get('last_status'))
print('paused_at:  ', a.get('paused_at'))
print('next_run_at:', a.get('next_run_at'))
print('last_error (first 500):', (a.get('last_error') or '')[:500])
"
```

If `last_error` contains "ran out of tool iterations" or "in-progress", your own run is the recovery. **Write the report file FIRST**, then run further probes — running probes first is what caused yesterday's iteration exhaustion.