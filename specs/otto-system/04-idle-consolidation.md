# Build Note 04 — Idle Consolidation

*Part of the Otto system. See 00-MASTER.md for the architectural context.*

## What it is

During idle periods, Otto runs maintenance on its own policy store:
- Merge near-duplicate policies into one stronger general policy
- Retire policies whose helped/hurt ratio has decayed below threshold
- Flag contradicting policies
- Output a short "maintenance report" so changes are visible

Maintenance, not growth. Sharpens what exists.

## Implementation

**File:** `~/.hermes/scripts/idle-consolidation.py`

**How it works:**
1. Load all policies from `~/.hermes/policies/pol-*.json`
2. **Duplicate detection:** Jaccard similarity on trigger strings (threshold 0.65)
3. **Retirement check:** helped/hurt ratio < 0.4 → candidate for retirement
4. **Contradiction detection:** one says "always X" and another says "never X"
5. **Promotion check:** provisional policies with hits >= 3 and helped > hurt
6. Output: `~/.hermes/logs/maintenance/YYYY-MM-DD.md`
