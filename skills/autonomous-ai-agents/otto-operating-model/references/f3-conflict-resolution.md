# F3 — Conflict Resolution (Built 2026-06-18)

## What it solves

Policy composition creates contradictions. "Specific overrides general" is the right default — but only safe if the specific policy's scope is correctly tight. Without F3, broad-scope specifics silently override good general rules.

## Architecture

### Phase 1: Scope analysis
Every policy is analyzed for scope tightness:
- **Tight**: contains an explicit condition (`if`, `when`, `while`, `unless`, `only if`, `scoped to`)
- **Broad**: uses absolute terms (`always`, `never`, `whenever`) without conditions
- **Unknown**: no clear scope signal

### Phase 2: Contradiction detection
Extracts DO/DON'T action verbs from every policy. Finds pairs where one says DO X and another says DON'T DO X with overlapping keywords.

### Phase 3: Resolution
- Specific over general (auto-resolve) — one has tight scope, the other vague
- Both same scope → escalated (cannot auto-resolve)
- Conflicts flagged in policy JSON files via `_conflicts` field

### Phase 4: Logging
Every conflict detection logged to `~/.hermes/logs/policy-conflicts.jsonl`.
Conflict reports generated to `~/.hermes/logs/maintenance/conflict-report-YYYY-MM-DD.md`.

## Files
- `~/.hermes/scripts/conflict-resolver.py` — the engine
- `~/.hermes/logs/policy-conflicts.jsonl` — conflict events

## Wired into
Idle pipeline (Phase 4b), runs every 2h after policy composition.

## Current state (2026-06-18)
9 policies analyzed: 8 tight, 1 vague (pol-002: "Always use background=true" — uses absolute term without scope condition).
0 contradictions found (no DO/DON'T conflicts yet).
