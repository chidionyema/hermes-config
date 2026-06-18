# B — Self-Detected Failure (Built 2026-06-18)

## What it solves

Otto detects its own failures without waiting for user correction. Before F1+F2 were live, this was dangerous — auto-policies from bad evals would flood the store. Now safe because:
- F1 (retrieval) prevents policy bloat — only relevant policies injected
- F2 (eval confidence) prevents gaming — low-confidence failures flagged for review, not auto-policy'd

## Architecture

### Trigger
`scripts/self-detect.py --scan` — scans the last 10 evaluation entries for FAIL status.

### On FAIL detection
1. Policy added via `otto-learn add` with trigger + rule describing the failure
2. `reflect-on-correction.py` called to update daily reflection
3. Failure added to regression corpus via `self-regression.py --add`
4. Evaluation entry marked `_self_detected: true` to prevent double-processing

### What does NOT trigger auto-policy
- LOW_CONFIDENCE status (confidence < 0.60) — these are flagged for human review
- Already-handled failures (marked `_self_detected`)
- PASS status (successes)

## Files
- `~/.hermes/scripts/self-detect.py` — the scanner + handler
- `~/.hermes/logs/eval-confidence.jsonl` — evaluation entries scanned by the detector

## Wired into
Idle pipeline (Phase 3b), runs every 2h after self-regression.
