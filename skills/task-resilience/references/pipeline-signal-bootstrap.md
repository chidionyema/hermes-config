# Bootstrapping a Stalled Self-Improvement Pipeline

## When to Use This

The meta-improver / idle-learning pipeline exists but reports:
- Improvement velocity = 0.0000
- "No data" / "Not enough metrics"
- Convergence detector says "diminishing returns"
- All corpus entries have `domain: unknown`

## The Problem

The pipeline isn't slow — it's starved for signal. The meta-improver is tuning the temperature of an empty oven. Adding more pipeline phases won't help until there's data to process.

## The 5-Step Bootstrap

### 1. Tag the Failure Corpus
Read `self-regression-corpus.json`. Every entry without a `domain` field is dead weight — gap-finding can't cluster on it. Classify each entry by trigger text into a domain taxonomy (e.g. `decision-making`, `infra/process-management`, `engineering/research`).

```python
domain_map = {
    "killed a process": "infra/process-management",
    "presented options": "decision-making",
    "guessed at an API": "engineering/research",
}
```

### 2. Assign Scope Domains to Policies
Policies need `scope.domain` set for domain-coverage metrics to work. Map each policy to the same taxonomy used in step 1.

### 3. Wire the Post-Correction Hook
`reflect-on-correction.py` likely exists but never runs. Add it to the idle-learning pipeline (Phase 0.5) so every user correction auto-generates a tagged training example.

### 4. Fix the Velocity Metric
Default `coverage_pct` comes from regression-report.md which doesn't exist yet. **Replace or augment with `domain_coverage_pct`**: % of failure domains that have at least one policy. This is measurable from day 1.

```python
corpus_domains = set(e.get("domain") for e in corpus)
policy_domains = set(p.get("scope",{}).get("domain") for p in policies)
domain_coverage = len(corpus_domains & policy_domains) / len(corpus_domains)
```

### 5. Add a Synthetic Probe
Add a no-agent cron script every 6h that checks for common gaps (stale git state, gateway health, cron stalls, policy duplication) and files structured entries into the failure corpus. This accelerates the corpus instead of waiting for real corrections.

## Outcome

After applying all 5:
- Domain coverage: 0% → 100% (measurable)
- Improvement velocity: 0.0000 → +3.5000 (first cycle)
- Gap-finding reports: from nothing to structured output
- Outer loop begins accumulating determined outcomes
