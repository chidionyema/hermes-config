---
name: research-workbench
description: "Research workflows spanning paper discovery, feed monitoring, linked knowledge bases, market-data exploration, and evidence-backed synthesis."
version: 1.0.0
author: Hermes Agent
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [research, arxiv, papers, rss, knowledge-base, markets, evidence]
---

# Research Workbench

Use this umbrella when the task is to find, monitor, organize, or synthesize external research and structured evidence.

## Workflow
1. Turn the question into searchable claims and define freshness and source-quality requirements.
2. Discover sources using the appropriate adapter: arXiv, RSS/blog feeds, linked markdown notes, or market APIs.
3. Capture identifiers, timestamps, URLs, and query parameters with every result.
4. Cross-check important claims against primary sources; distinguish observation, inference, and speculation.
5. Produce the requested output with citations and a reproducible retrieval trail.

## Adapters
- **Papers**: search by title/author/category/ID, fetch the abstract or PDF, and retain the canonical identifier.
- **Feeds**: maintain stable feed URLs, deduplicate by GUID/link, and record publication time.
- **Knowledge bases**: preserve links between notes and avoid duplicating canonical facts.
- **Market data**: treat prices/order books as time-sensitive observations; include snapshot time and units.

Do not present stale or unverifiable data as current fact.
