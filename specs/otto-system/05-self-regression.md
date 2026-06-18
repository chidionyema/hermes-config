# Build Note 05 — Self-Regression

*Part of the Otto system. See 00-MASTER.md for the architectural context.*

## What it is

A regression suite of Otto's own mistakes. Maintains a corpus of past failures and re-tests the current policy set against them. Pass = evidence a policy is working (feeds promotion). Fail = gap still open.

## Implementation

**File:** `~/.hermes/scripts/self-regression.py`
**Corpus:** `~/.hermes/logs/self-regression-corpus.json`

**How it works:**
1. **Corpus harvesting:** Extracts failures from daily reflections + policy firing logs
2. **Regression testing:** For each corpus entry, check if any active/provisional policy covers it by word overlap
3. **Coverage tracking:** Covered/total = coverage %
4. **Reporting:** `~/.hermes/logs/regression-report.md`

**Current baseline:** 2/8 (25%) — measured and verified.

## What feeds the corpus
- Policy firings from `policy-firings.jsonl`
- Corrections extracted from daily reflections
- Manual additions via `--add "trigger" "fix"`
