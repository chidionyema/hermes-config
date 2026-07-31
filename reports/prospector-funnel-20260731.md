# Prospector funnel diagnosis — 2026-07-31 (operator)

**Repo HEAD:** `b21a3ca` branch `discovery-ux-2026-07-30`  
**Baseline suite:** `662 passed, 11 failed` (ignore control_center collection) — see `prospector-baseline-20260731.md`

## Funnel table (thresholds with file:line)

| Stage | File | Decision threshold | Notes |
|---|---|---|---|
| Prescreen | `prospector/prescreen.py:112-150` | structural auto-reject before LLM; bias keep on uncertainty | `return True, "passed structural filter"` @150 |
| Kill filter | `prospector/kill_filter.py:43` | `confidence >= cfg.thresholds.confidence_floor` | Top-level `confidence_floor: 0.0` (`config.yaml:149`) — **KILL lever currently OFF** |
| Score | `prospector/score.py:18-55` | composite Σ(score×weight); pass if `composite >= min_composite_to_pass` | `min_composite_to_pass: 2.5` (`config.yaml:160`) |
| Novelty | `prospector/novelty.py:47` | DPP: `prescreen_score * exp(-λ max sim)` | diversity select, not hard kill |
| Pass ceiling | `prospector/pass_ceiling.py:7-21` | `min_supported_to_pass`, `min_supported_confidence: 0.3`, composite ceiling | source-or-die early exit |
| Golden | `prospector/golden.py:46-80` | surface threshold 0.7; haulage → KILL | fixture-driven |

**Lane overrides:** growth/venture use `confidence_floor: 0.4` (`config.yaml:234`); smb/side lanes often `0.0` pending calibration.

## Observed from fixtures
- `fixtures/golden_set.json` present (1411 bytes)
- Highest-leverage gap for next ship: **Stripe bridge test cluster** (4 fails in `tests/test_engine_bridge.py`) — not funnel thresholds themselves

## Acceptance for THIS milestone
`test -s ~/.hermes/reports/prospector-funnel-20260731.md && grep -c 'confidence.yaml' ~/.hermes/reports/prospector-funnel-20260731.md` → >0

## BLOCKER for auto-exec
Claude/agy **quota exhausted** (~105h reset). Mission advances on operator-written evidence only until quota returns.
