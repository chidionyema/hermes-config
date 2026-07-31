# Prospector — product next-move (baseline-backed)

**Date:** 2026-07-31 04:24  
**Baseline:** ~/.hermes/reports/prospector-baseline-20260731.md  
**HEAD:** `b21a3ca`  
**Suite:** `python3 -m pytest tests --ignore=tests/control_center -q` → **11 failed, 662 passed, 2 skipped**

## 1. The one objective

Fix the **highest-leverage failing cluster** with cited evidence: `tests/test_engine_bridge.py` Stripe provisioner / provider-selection failures (4 fails), before UI-theme cosmetic fails.

## 2. Acceptance test

```bash
cd ~/Documents/code/prospector && python3 -m pytest tests/test_engine_bridge.py -q
```
**Done when:** that file goes from RED (current 4 FAILED) to green (0 failed). Re-run core suite and paste verdict line + `git rev-parse --short HEAD`.

## 3. Files to touch

- `prospector/bridge.py` (already dirty on branch)
- Stripe provisioner path exercised by `tests/test_engine_bridge.py`
- Do **not** expand scope into control_center collection errors in this pass

## 4. Risks / rollback

- Money-adjacent Stripe test doubles — keep changes test-scoped; no live Stripe calls.
- Rollback: `git checkout --` on touched files if core suite regresses below 662 passed.

## STATUS
- Baseline captured: YES
- Implemented: NO (Claude quota blocked executor; human/agent baseline only)
- Reproduce: `python3 -m pytest tests --ignore=tests/control_center -q` → expect ~11 failed, 662 passed, 2 skipped at `b21a3ca`


## STATUS (2026-07-31 operator)
- Funnel diagnosis: DONE → `/Users/chidionyema/.hermes/reports/prospector-funnel-20260731.md`
- Next acceptance: `python3 -m pytest tests/test_engine_bridge.py -q` (currently RED, 4 fails)
- BLOCKER: Claude quota — do not spin mission-steps until reset
- Reproduce baseline: `python3 -m pytest tests --ignore=tests/control_center -q`
