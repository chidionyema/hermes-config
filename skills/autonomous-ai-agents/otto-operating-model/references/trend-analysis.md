# Cross-Session Trend Analysis

## Purpose

The trend analyzer (`~/.hermes/scripts/trend-analyzer.py`) compares data across days to find week-level patterns that no single-day snapshot can detect. It's designed to be useless at day 1 and increasingly valuable as data accumulates.

## Data Sources

| Source | Path | What it provides |
|---|---|---|
| Daily reflections | `logs/reflection/*.md` | Improvement items, correction counts per day |
| Near-miss reports | `logs/maintenance/near-miss-*.json` | Untriggered policies per scan, co-firing patterns |
| Task outcomes | `logs/outcomes/task-outcomes.jsonl` | Every task that completed, with type and policies fired |
| Corpus | `logs/self-regression-corpus.json` | Domain growth over time (via `added_at` dates) |
| Meta-improver outcomes | `meta/change-outcomes.jsonl` | Velocity and determined outcome history |

## What It Detects (once data accumulates)

- **Persistently untriggered policies** — same policy appearing in >2 consecutive near-miss scans → suggest archiving or rewriting
- **Declining outcome velocity** — improvement outcomes outpaced by general outcomes → suggest explicit improvement tasks
- **Corpus not growing** — same domains appearing day after day → probe may need broader scanning
- **Recurring failure patterns** — same correction domain appearing across multiple days

## When to Run

- Runs as Phase 5 of the idle-learning pipeline (every 2h)
- Can run standalone: `uv run python3 ~/.hermes/scripts/trend-analyzer.py`
- Results written to `logs/trends/trend-YYYYMMDD-HHMMSS.json`

## Output Schema

```json
{
  "generated_at": "...",
  "days_analyzed": 3,
  "total_outcomes": 47,
  "outcome_velocity_per_day": 15.7,
  "persistently_untriggered_policies": [
    {"policy_id": "pol-20260618-002", "appearances_in_near_miss": 4}
  ],
  "corpus_domain_growth": {
    "2026-06-18": ["decision-making", "infra/..."],
    "2026-06-19": ["decision-making", "infra/...", "testing"]
  },
  "recurring_patterns": ["Policy pol-20260618-002 untriggered in 4 consecutive scans"],
  "suggested_improvements": ["Consider archiving pol-20260618-002 — untriggered in 4 scans"]
}
```

## Known Limitation

With only 1-2 days of data, `days_analyzed` will be <2 and most fields will be empty or 0. This is expected — the scaffold exists now and will fill as data accumulates. The pipeline is designed to detect trends, not generate them from thin air.
