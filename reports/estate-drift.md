# Estate Drift Report
**Generated:** 2026-07-31 06:00:44
**Baseline:** estate-20260730-061352.json

**Changes detected:** **4 warnings**, 16 info items

## 🟡 Warning
- Policy never fired: pol-auto-engineering-reliability-20260730 (domain=engineering/reliability)
- Policy never fired: pol-auto-meta-reflection-20260730 (domain=meta/reflection)
- Policy never fired: repo-dirty-uncommitted (domain=?)
- Policy never fired: test-timeout-investigate (domain=?)

## 🔵 Info
- New script: ceo_mode.py
- New script: corpus_hygiene.py
- New script: cron-job-health-probe.py
- New script: learning_switch.py
- New script: morning_brief.py
- New cron job: weekly-progress-digest (0 18 * * 0)
- Policy not gaining hits: pol-20260618-001 (still at 2)
- Policy not gaining hits: pol-20260618-007 (still at 1)
- Policy not gaining hits: pol-20260618-008 (still at 1)
- New policy: pol-auto-engineering-reliability-20260730 (domain=engineering/reliability)
- New policy: pol-auto-meta-reflection-20260730 (domain=meta/reflection)
- New policy: repo-dirty-uncommitted (domain=?)
- New policy: test-timeout-investigate (domain=?)
- Policy removed: pol-auto-engineering-reliability-20260722
- Policy removed: pol-auto-meta-reflection-20260722
- Config changed: hash 501bf6b80a45 → 53743718830d

## Estate Summary
- **Scripts:** 131
- **Skills:** 88
- **Cron jobs:** 23
- **Policies:** 7
- **Config version:** 53743718830d

## Action Items
- [ ] Review/archive policy: pol-auto-engineering-reliability-20260730 (domain=engineering/reliability)
- [ ] Review/archive policy: pol-auto-meta-reflection-20260730 (domain=meta/reflection)
- [ ] Review/archive policy: repo-dirty-uncommitted (domain=?)
- [ ] Review/archive policy: test-timeout-investigate (domain=?)