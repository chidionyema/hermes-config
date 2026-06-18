# Build Note 03 — Memory Retrieval Phase 2

*Part of the Otto system. See 00-MASTER.md for the architectural context.*

## What it is

The self-query memory retrieval layer that injects relevant memories and active policies into every strategist dispatch. Phase 2 implements tag-based routing with confidence scoring.

## Implementation

**File:** `~/.hermes/scripts/memory_retrieval.py`

**Logic:**
1. On every strategist dispatch, parse the task description against keyword heuristics
2. Match against project/domain/type tags in MEMORY.md
3. Score each entry (0.0-1.0), accept >= 0.5
4. Inject: INVARIANTS + RETRIEVED MEMORY + ACTIVE POLICIES + USER PROFILE
5. Log the injection to `~/.hermes/logs/injection-log.jsonl`

## Why Phase 2 was critical

The entire policy enforcement system depends on active policies being injected into context during strategist calls. Phase 1 (design) was done. Phase 2 (the actual working implementation) was deferred "until store exceeds 10 entries" — but the policy system couldn't function without it. Phase 2 is now live.
