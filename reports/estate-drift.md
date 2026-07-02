# Estate Drift Report
**Generated:** 2026-07-02 06:01:01
**Baseline:** estate-20260623-061000.json

**Changes detected:** **1 warnings**, 17 info items

## 🟡 Warning
- Policy never fired: pol-auto-engineering-reliability-20260701 (domain=engineering/reliability)

## 🔵 Info
- New script: cockpit-daemon.sh
- New script: handoff-gate.sh
- New script: ngrok-daemon.sh
- New script: otto-daemon.sh
- New script: verify_estate.sh
- Skill removed: otto-coordinator-rules-2026-06-18
- Policy not gaining hits: pol-20260618-001 (still at 2)
- Policy not gaining hits: pol-20260618-004 (still at 1)
- Policy not gaining hits: pol-20260618-007 (still at 1)
- Policy not gaining hits: pol-20260618-008 (still at 1)
- New policy: pol-auto-engineering-reliability-20260701 (domain=engineering/reliability)
- Policy removed: pol-20260618-002
- Policy removed: pol-20260618-003
- Policy removed: pol-20260618-006
- Policy removed: pol-20260618-010
- Policy removed: pol-20260618-012
- Policy removed: pol-auto-engineering-reliability-20260618

## Estate Summary
- **Scripts:** 126
- **Skills:** 87
- **Cron jobs:** 22
- **Policies:** 5
- **Config version:** 501bf6b80a45

## Action Items
- [ ] Review/archive policy: pol-auto-engineering-reliability-20260701 (domain=engineering/reliability)