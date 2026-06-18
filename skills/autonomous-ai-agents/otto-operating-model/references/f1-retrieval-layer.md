# F1 — Retrieval Layer (Phase 3, Built 2026-06-18)

## Architecture

Three-tier retrieval that runs before every strategist dispatch:

1. **Self-query routing** (`route_query()`) — classifies task by domain triggers to decide what to retrieve (policies vs memory vs both vs neither)
2. **Tag filter** (`retrieval/tag_filter.py`) — keyword first-pass against project/domain/type schemas
3. **Embedding recall** (`retrieval/embedding_recall.py`) — all-MiniLM-L6-v2 ONNX, 384-dim cosine similarity

## Files

- `~/.hermes/scripts/retrieval/__init__.py` — package
- `~/.hermes/scripts/retrieval/tag_filter.py` — keyword scoring (project/domain/type tags + content overlap)
- `~/.hermes/scripts/retrieval/embedding_recall.py` — EmbeddingIndex, cosine similarity, routing, payload builder
- `~/.hermes/scripts/memory_retrieval.py` — CLI entry point (unchanged interface)
- `~/.hermes/models/miniLM-onnx/` — ONNX model + tokenizer (86MB)
- `~/.hermes/logs/retrieval/embedding_cache.pkl` — disk cache (auto-rebuilds)

## Scale properties

| Metric | Value |
|--------|-------|
| Embedding dim | 384 |
| Query time (12 entries) | ~1s (first load, includes model init) |
| Query time (cached) | ~50ms |
| Expected at 900 policies | ~1ms (numpy dot product) |
| Model size | 86MB (ONNX) |
| Cache size | ~42KB at 12 entries |
| Fallback | Tag-filter only if ONNX unavailable |

## Routing decisions

| Task type | Policies | Memory | Notes |
|-----------|----------|--------|-------|
| Dispatch/delegate | ✅ | ✅ | Also pulls background=true, ACT-not-SURFACE policies |
| Bug fix | ✅ | ✅ | Pulls correction policies |
| Trading/market | ❌ | ❌ | Domain mismatch penalty (+0.15 threshold) |
| State query | ❌ | ✅ | No policy injection needed |
| Infrastructure | ✅ | ✅ | Config, cron, skill, memory triggers |
| Idle/consolidation | ✅ | ✅ | Pulls all policy-relevant rules |

## Test results (2026-06-18)

Nine policies in store. Domain-mismatch queries correctly return 0 policies.
Dispatch queries return 4 relevant policies including pol-002 (background=true) and pol-005 (ACT not SURFACE).
Low-relevance policies score below threshold and are excluded.

## CoreML note

The ONNX model failed on CoreMLExecutionProvider (macOS compatibility issue).
Fallback: uses only CPUExecutionProvider. ~1s per 12-entry batch, acceptable for pre-dispatch calls.
