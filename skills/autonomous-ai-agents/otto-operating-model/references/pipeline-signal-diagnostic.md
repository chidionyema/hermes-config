# Pipeline Signal Diagnostic — Starved-Pipeline Detection

## When the meta-improver lies to you

The meta-improver reports `improvement velocity: +0.0000 coverage_pct/cycle` and `Pipeline may have converged or reached diminishing returns` when it's actually **starved for signal** — not optimized.

This is the most common false-negative in the self-improvement system: convergence detection has no way to distinguish "optimized" from "never had data."

## Diagnostic checklist

When improvement velocity is flat at 0:

### 1. Failure corpus state

```bash
python3 -c "
import json
p = '/Users/chidionyema/.hermes/logs/self-regression-corpus.json'
with open(p) as f:
    data = json.load(f)
domains = {}
for e in data:
    d = e.get('domain', 'unknown')
    domains[d] = domains.get(d, 0) + 1
print(f'{len(data)} entries, {len(domains)} unique domains')
for d, c in sorted(domains.items(), key=lambda x: -x[1])[:10]:
    print(f'  {d}: {c}')
"
```

**Good signal:** 3+ domains with 2+ failures each, no `unknown` in top 5.
**Starved:** all entries `unknown`, or <=5 total entries.

### 2. Gap-finding output

```bash
ls -t ~/.hermes/logs/maintenance/gap-finding-*.json 2>/dev/null | head -1 | xargs -I{} python3 -c "
import json
with open('{}') as f:
    d = json.load(f)
print(f'Uncovered: {len(d.get(\"uncovered_domains\",[]))}')
print(f'Weak coverage: {len(d.get(\"weak_coverage\",[]))}')
for item in d.get('uncovered_domains',[]):
    print(f'  {item.get(\"domain\",\"?\")}: {item.get(\"failure_count\",0)} failures')
"
```

**Good:** at least one uncovered domain or weak-coverage entry.
**Starved:** no gap-finding reports exist, or they return empty lists.

### 3. Change outcomes

```bash
lines=$(wc -l < ~/.hermes/meta/change-outcomes.jsonl 2>/dev/null || echo 0)
echo "$lines change outcomes"
python3 -c "
import json
with open('/Users/chidionyema/.hermes/meta/change-outcomes.jsonl') as f:
    for l in f:
        d = json.loads(l)
        print(f'  {d.get(\"change_type\",\"?\")}: {d.get(\"outcome\",\"?\")}')
" 2>/dev/null || echo "No outcomes file"
```

**Good:** 5+ determined outcomes (improved/degraded/neutral), at least 2 HIGH_YIELD change types.
**Starved:** 0-2 outcomes, all "pending."

### 4. Ontology check — policies with domain scope

```bash
python3 -c "
import json, os
policy_dir = '/Users/chidionyema/.hermes/policies'
total = 0
with_scope = 0
for fname in os.listdir(policy_dir):
    if not fname.endswith('.json'): continue
    with open(os.path.join(policy_dir, fname)) as f:
        p = json.load(f)
    total += 1
    if p.get('scope',{}).get('domain'):
        with_scope += 1
print(f'{total} policies, {with_scope} with domain scope')
"
```

**Good:** >60% of policies have a domain scope.
**Starved:** most policies have empty `scope: {}`.

## Acceleration interventions (when starved)

### Immediate (works in 5 min)

**1. Tag the failure corpus.** Classify every entry by domain so gap-finding has signal. Classification heuristic: match trigger text against known patterns (decision-making, infra/process-management, engineering/research, etc.). Entries from reflection markdown scraping with noise triggers (e.g. "| Fixed? |") should be classified as `meta/reflection`. Firing-log entries match against the policy trigger text directly.

Run once, then force a full idle-learning cycle.

**2. Force a meta-improver full cycle:**
```bash
uv run python3 ~/.hermes/scripts/meta-improver.py --full-cycle
```
If the script hash check fails, meta-improver.py was modified. Bootstrap the new hash:
```bash
uv run python3 ~/.hermes/scripts/meta-improver.py --bootstrap-hash
```
Then retry the full cycle.

### Medium-term

**3. Wire post-correction hook into runtime.** `reflect-on-correction.py` exists but runs only when manually invoked in the user-correction protocol. Add it as Phase 0.5 in `idle-learning-run.sh` — placed between preflight and meta-improvement:
```bash
# ── Post-Correction Reflection Hook ──────────────────────────────
echo "--- Phase 0.5: Post-Correction Reflection ---"
check_preempt
"$VENV_PYTHON" "$HERMES_HOME/scripts/reflect-on-correction.py" 2>&1 || true
```

**4. Replace the velocity metric** with `domain_coverage_pct` — fraction of the failure corpus domains that have at least one policy. This starts >0 immediately after tagging the corpus, unlike `coverage_pct` which is flat at 0 until enough policies accumulate. Patches needed in `meta-improver.py`:
- Add `domain_coverage_pct` computation in `cmd_postflight()`: load corpus, extract unique domains, intersect with policy scope.domains, compute percentage
- Emit `domain_coverage_pct` alongside `coverage_pct` in the postflight metric entry
- Also assign `scope.domain` to every existing policy — the meta-improver can't compute domain coverage if policies lack scope

**5. Add a synthetic probe.** A no-agent cron job every 6h running heuristics (git branch divergence, gateway health, cron stalls, policy duplication) that writes structured findings. The probe is passive — it logs but never acts. Findings are consumed by gap-finding on the next idle cycle.

Cron job config: no-agent script `improvement-probe.sh`, every 360m, deliver to origin.

### Long-term

**6. Cross-session trend analysis.** Weekly aggregator comparing reflection outputs across days to spot recurring patterns.
