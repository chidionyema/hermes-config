# Memory Hygiene — Keeping Under the 2,200-Character Limit

The durable memory store is capped at 2,200 characters. When full, new saves fail. This doc covers compaction discipline.

## Warning signs

- `memory()` returns "Memory at N/2,200 chars" where N > 2,000
- You're about to save something but hesitate because "do I have room?"
- The most recent save was a memory-add, not a memory-replace

## Compaction ritual (fire when >90% full)

1. **Tag-audit:** list all entries in memory. Group by `[tags:]` prefix — what projects/domains overlap?
2. **Merge stale project state:** replace multiple entries for the same project with one compact line. Example:
   - `"Prospector go-live: 362 pass, .NET 39 ..."` ✅ compact
   - Three separate entries for Prospector ❌ wasteful
3. **Stale detail → archive to skill ref:** if a memory entry contains session-specific detail (SHA hashes, PR numbers, exact file counts), move it to the relevant skill's `references/` directory instead and replace the memory entry with just a pointer: `[tags: project:X] See skill Y references/...`
4. **Prompt-stage instructions → delete:** memory entries that say "remember to do X" or "don't do Y next time" should be policies (in `~/.hermes/policies/`) not memory. Remove from memory.
5. **Temporary task state → delete:** if you find entries like "currently working on Z" or "was interrupted doing W", kill them — task_resilience handles this on disk, not memory.
6. **Prefer `memory(replace)` over `memory(add)`** for updates — every new `add` pushes you toward the limit. Replacing compacts.
7. **After compaction, verify:** check that the essential facts (model, invariants, key projects) survived. If a project entry got deleted because it was too detailed and you didn't archive it, you'll lose context on next session start.

## What belongs in memory vs references vs policies vs skills

| Store | Purpose | Size limit | Cadence |
|-------|---------|------------|---------|
| **memory** | Durable cross-session facts: user preferences, environment details, project state summaries, tool quirks, stable conventions | 2,200 chars | Changed when facts change |
| **policies/** | Correction rules: what-not-to-do, what-to-do-instead | Per-file, no strict limit | New policy per correction |
| **skills/** | Procedural knowledge: how to do a class of task | Unlimited (SKILL.md + refs) | Created/patched per session signal |
| **task-resilience** | Current-task progress, per-tool-call state | Per-file, no strict limit | Per tool call, cleared on finish |

## The eviction priority (what gets cut first)

1. **Absolute oldest** — if the user hasn't mentioned a project in 30 days, it doesn't need to be in memory
2. **Most detail-heavy** — SHAs, version numbers, line counts. Move to skill ref.
3. **Most verbose** — entries with long sentences. Compact them.
4. **Least-often injected** — if memory retrieval uses tag-based scoring, low-scored entries get evicted first on conflict

## Practical: the 2,200-char budget

Approximate allocations for a healthy memory:

- Invariants (6 rules): ~400 chars
- Model config: ~200 chars
- User profile: ~500 chars (stored separately)
- Per active project: ~300-400 chars each (max 3 projects)
- Current task note: ~100 chars
- **Total target:** ~1,800-1,900 chars (leaves 300-400 headroom for mid-session saves)
