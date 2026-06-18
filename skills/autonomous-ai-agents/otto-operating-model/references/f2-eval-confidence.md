# F2 — Eval Regression (Phase 4, Built 2026-06-18)

## What it solves

The most dangerous bottleneck in the Radical Improvement Plan. Self-detection (B) + a gameable eval = optimising for the wrong thing *at speed*. The policy store fills with rules that satisfy the metric and defeat the intent (Goodhart).

## Architecture

### Confidence spectrum (replaces binary PASS/FAIL)

Each task outcome is scored 0.0–1.0 from four factors:

| Factor | Weight | Details |
|--------|--------|---------|
| Exit code | ±0.25 | 0→+0.25, 1→-0.10, signal→-0.20 |
| Criteria specificity | ±0.25 | Based on keyword analysis + word count |
| Output file | ±0.10 | +0.10 if exists, -0.15 if missing |
| Task duration | ±0.05 | Suspiciously fast/slow deductions |

Thresholds: ≥0.85 high, ≥0.60 medium, <0.60 flagged, <0.30 structural fail.

### Passive divergence detection

When the user corrects Otto, the correction protocol records:
- `otto_grade`: Otto's self-assigned confidence at evaluation time
- `user_grade`: 0.0 (correction = failure by default)

If divergence ≥ 0.3, it's a divergence event. After 5+ events, if >20% diverged, drift is flagged.

### Holdout corpus

Built entirely from corrections. No separate grading UI. No manual data entry.
Stored at `~/.hermes/logs/eval-holdout.json`, last 50 entries.

## Files

- `~/.hermes/scripts/eval-confidence.py` — scoring engine + divergence detection + health report + CLI
- `~/.hermes/scripts/outcome-evaluator.py` — rewritten to use confidence spectrum (F2-aware)
- `~/.hermes/logs/eval-confidence.jsonl` — every scored evaluation
- `~/.hermes/logs/eval-divergence.jsonl` — divergence events only
- `~/.hermes/logs/eval-holdout.json` — human-grade holdout corpus

## User correction protocol (updated)

The correction protocol in SKILL.md now records F2 divergence as step 1:
```
python3 ~/.hermes/scripts/eval-confidence.py --record-user-grade \
  "<task_id>" 0.0 "User correction: <brief summary>"
```

## Design principle

Passive > active. Zero-friction for the user. The holdout corpus is a side effect of existing behaviour (corrections), not a new workflow. F2 is silent until drift is detected.
