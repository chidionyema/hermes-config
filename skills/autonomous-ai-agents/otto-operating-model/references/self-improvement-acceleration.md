# Self-Improvement Acceleration — Architecture Overview

## Problem: Pipeline Starved for Signal

The idle continuous learning pipeline reported `improvement velocity: +0.0000` and "diminishing returns" when the real problem was **no data to process**. All 14 failure corpus entries had `domain: unknown`, so gap-finding had nothing to cluster on.

## Five Interventions (applied 2026-06-18)

| # | Intervention | What | Impact |
|---|---|---|---|
| 1 | **Tag failure corpus** | Classify every entry by domain (decision-making, infra, engineering, meta) | Gap-finding now has 6 domains to cluster on |
| 2 | **Wire post-correction hook** | `reflect-on-correction.py` runs every idle cycle as Phase 0.5 | Reflection mechanism works even without user-correction protocol |
| 3 | **Force full meta-improver cycle** | `--full-cycle` after bootstrapping hash | Velocity went 0 → +3.5, domain coverage 0% → 100% |
| 4 | **Dual velocity metric** | `domain_coverage_pct` as primary signal alongside `coverage_pct` | Measurable from day 1 (was flat at 0) |
| 5 | **Synthetic probe** | `improvement-probe.sh` every 6h scans for gaps | Generates training data without waiting for real corrections |

## Current Pipeline Data Flow

```
User corrections → reflect-on-correction.py (Phase 0.5)
Task completions → outcome-accelerator.py → change-outcomes.jsonl
Improvement-probe (every 6h) → probe findings logged to corpus
                    ↓
              idle-learning-run.sh (every 2h)
                    ↓
        meta-improver --analyze (inner + outer loop)
                    ↓
        gap-finding → near-miss analysis → self-regression
                    ↓
              Postflight: dual metrics logged
```

## Key Files

- `~/.hermes/scripts/outcome-accelerator.py` — logs every task completion as outcome
- `~/.hermes/scripts/near-miss-analyzer.py` — finds untriggered policies, co-firing contexts
- `~/.hermes/scripts/improvement-probe.sh` — synthetic probe, no-agent cron
- `~/.hermes/skills/task-resilience/task_state.py` — wired to call outcome accelerator on `mark_task_complete()`
- `~/.hermes/meta/change-outcomes.jsonl` — consumed by meta-improver outer loop
- `~/.hermes/logs/outcomes/task-outcomes.jsonl` — full task outcome history

## Diagnostic Commands

```bash
# Check policy hit rates
python3 -c "
import json, os
for fname in sorted(os.listdir('~/.hermes/policies')):
    if fname.endswith('.json'):
        with open(f'~/.hermes/policies/{fname}') as f:
            p = json.load(f)
        print(f'{p[\"id\"]}: hits={p.get(\"hits\",0)} domain={p.get(\"scope\",{}).get(\"domain\",\"none\")}')
"

# Check corpus freshness
python3 -c "
import json
with open('~/.hermes/logs/self-regression-corpus.json') as f:
    c = json.load(f)
from collections import Counter
domains = Counter(e.get('domain','?') for e in c)
for d,n in domains.most_common():
    print(f'  {d}: {n}')
print(f'Total: {len(c)} entries')
"

# Check outcome determination
python3 -c "
import json
with open('~/.hermes/meta/change-outcomes.jsonl') as f:
    outcomes = [json.loads(l) for l in f if l.strip()]
statuses = Counter(o.get('outcome','?') for o in outcomes)
for s,n in statuses.most_common():
    print(f'  {s}: {n}')
print(f'Total: {len(outcomes)}')
"
```
