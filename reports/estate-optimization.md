# Estate Optimization Report
**Generated:** 2026-06-18 13:51:32
**Sources:** 5 bottleneck reports, 1 near-miss, 1 trends, 9 alerts, 2 policies

## 🟠 High Priority
- **Alert type '?' fired 9 times**
  → Recurring issue — needs root cause fix, not symptom handling

## 🟡 Medium Priority
- **7 policies have never triggered**
  → Consider archiving or rewriting: pol-20260618-002, pol-20260618-003, pol-20260618-004, pol-20260618-006, pol-20260618-008
- **5 contexts detected with multiple policies firing together**
  → These policies may overlap — consider merging or clarifying scope

## Actions Required
- [x] `archive_dead_policies` — highest priority: medium
- [x] `consolidate_overlapping_policies` — highest priority: medium
- [x] `fix_recurring_?` — highest priority: high
- [ ]] `optimize_policy_pol-20260618-007` — highest priority: info

## Data Health
- Meta-improver bottlenecks: 5
- Near-miss analysis: ✅ available
- Trend data: ✅ available
- Watchdog alerts: 9
- Policy firing data: ✅ available
- **Total recommendations:** 4