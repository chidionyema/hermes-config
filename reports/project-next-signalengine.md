# Signal Engine — product next-move (M7 proof landed)

**Date:** 2026-07-31 04:24  
**Proof:** ~/.hermes/reports/signal-m7-readiness-20260731.md — M7 readiness **GREEN** at `fddef58`.

## 1. The one objective

Land the next **M7-Live ship item** that is still RED in VERIFICATION_MATRIX / README after readiness green — prefer a failing POPDD / reconciliation gap with a runnable pytest acceptance, not another plan essay.

## 2. Acceptance test

```bash
cd ~/Documents/code/signalengine && uv run pytest tests/test_m7_readiness.py -q && uv run python scripts/popdd_verify.py
```
Exit 0 on both. Paste stdout tails + HEAD SHA.

## 3. Files to touch
TBD after reading matrix gaps — **money fence**: no live orders / keys without founder approve.

## 4. Risks
Money class — awaiting_approval before any mutation.
