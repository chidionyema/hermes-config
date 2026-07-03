# Estate Optimization Report
**Generated:** 2026-07-03 06:04:47
**Sources:** 5 bottleneck reports, 1 near-miss, 1 trends, 20 alerts, 2 policies

## 🟠 High Priority
- **Alert type 'CRON_ERROR' fired 19 times**
  → Recurring issue — needs root cause fix, not symptom handling

## 🟡 Medium Priority
- **5 contexts detected with multiple policies firing together (unrelated to escalation chains)**
  → These policies may genuinely overlap — consider merging or clarifying scope
- **Recurring pattern: Policy pol-20260618-004 appears untriggered in 276 consecutive near-miss scans**
  → Occurred ? times — consider automating this
- **Recurring pattern: Policy pol-20260618-008 appears untriggered in 276 consecutive near-miss scans**
  → Occurred ? times — consider automating this
- **Recurring pattern: Policy pol-20260618-002 appears untriggered in 220 consecutive near-miss scans**
  → Occurred ? times — consider automating this

## Actions Required
- [x] `automate_pattern` — highest priority: medium
- [x] `consolidate_overlapping_policies` — highest priority: medium
- [x] `fix_recurring_cron_error` — highest priority: high
- [ ]] `optimize_policy_pol-20260618-007` — highest priority: info
- [ ]] `review_suggestion` — highest priority: info

## Data Health
- Meta-improver bottlenecks: 5
- Near-miss analysis: ✅ available
- Trend data: ✅ available
- Watchdog alerts: 20
- Policy firing data: ✅ available
- **Total recommendations:** 9