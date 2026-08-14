# Estate Optimization Report
**Generated:** 2026-08-14 06:00:19
**Sources:** 5 bottleneck reports, 1 near-miss, 1 trends, 20 alerts, 10 policies

## 🟠 High Priority
- **Alert type 'CRON_ERROR' fired 20 times**
  → Recurring issue — needs root cause fix, not symptom handling

## 🟡 Medium Priority
- **139 policies have never triggered**
  → Consider archiving or rewriting: pol-20260618-008, pol-auto-engineering-reliability-20260807, pol-auto-fix-config_push, pol-auto-meta-reflection-20260807, pol-auto-unknown-20260810
- **7 contexts detected with multiple policies firing together (unrelated to escalation chains)**
  → These policies may genuinely overlap — consider merging or clarifying scope
- **Recurring pattern: Policy pol-20260618-008 appears untriggered in 542 consecutive near-miss scans**
  → Occurred ? times — consider automating this
- **Recurring pattern: Policy pol-20260618-004 appears untriggered in 283 consecutive near-miss scans**
  → Occurred ? times — consider automating this
- **Recurring pattern: Policy pol-auto-fix-config_push appears untriggered in 249 consecutive near-miss**
  → Occurred ? times — consider automating this

## Actions Required
- [x] `archive_dead_policies` — highest priority: medium
- [x] `automate_pattern` — highest priority: medium
- [x] `consolidate_overlapping_policies` — highest priority: medium
- [x] `fix_recurring_cron_error` — highest priority: high
- [ ]] `optimize_policy_pol-20260618-007` — highest priority: info
- [ ]] `optimize_policy_pol-auto-fix-coordinator` — highest priority: info
- [ ]] `optimize_policy_pol-auto-prospector-moat-202608021736` — highest priority: info
- [ ]] `optimize_policy_pol-auto-prospector-moat-202608021740` — highest priority: info
- [ ]] `optimize_policy_pol-auto-prospector-moat-202608022008` — highest priority: info
- [ ]] `optimize_policy_pol-auto-prospector-moat-202608022017` — highest priority: info
- [ ]] `review_suggestion` — highest priority: info

## Data Health
- Meta-improver bottlenecks: 5
- Near-miss analysis: ✅ available
- Trend data: ✅ available
- Watchdog alerts: 20
- Policy firing data: ✅ available
- **Total recommendations:** 15