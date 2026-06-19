# Estate Drift Report
**Generated:** 2026-06-19 06:00:32
**Baseline:** estate-20260618-141310.json

**Changes detected:** **6 warnings**, 51 info items

## 🟡 Warning
- Policy never fired: pol-20260618-002 (domain=infra/dispatch)
- Policy never fired: pol-20260618-003 (domain=decision-making)
- Policy never fired: pol-20260618-006 (domain=engineering/research)
- Policy never fired: pol-20260618-010 (domain=engineering/verification)
- Policy never fired: pol-20260618-012 (domain=infra/dispatch)
- Policy never fired: pol-auto-engineering-reliability-20260618 (domain=engineering/reliability)

## 🔵 Info
- New script: alert-resolver-probe.sh
- New script: alert-resolver.py
- New script: closed-loop-proof.sh
- New script: daemon-stability-probe.sh
- New script: dropped-ball-probe.sh
- New script: dropped-ball-tracker.py
- New script: hermes_claims.py
- New script: hermes_fingerprint.py
- New script: hermes_queue.py
- New script: idle-curiosity.py
- New script: idle-learning-probe.sh
- New script: known_classes.py
- New script: memory-capacity-probe.sh
- New script: memory-hygiene.py
- New script: mentor-reflect.py
- New script: methodology-probe.sh
- New script: otto-correction-scan-probe.sh
- New script: otto-correction-scan.py
- New script: otto-dispatch-probe.sh
- New script: otto-dispatch.py
- New script: otto-dispatch.sh
- New script: popdd-init.sh
- New script: prospector-run.sh
- New script: proving-ground-probe.sh
- New script: proving-ground.py
- New script: publish-lux-stack.sh
- New script: pytest-orphan-cleanup.sh
- New script: queue-curate.sh
- New script: queue-probe.sh
- New script: signal-engine-daemon-watchdog.sh
- New script: signal-engine-watchdog-probe.sh
- New script: skill-hygiene.py
- New script: watchdog-probe.sh
- New script: weekly-progress-digest.py
- New skill added: dropped-ball-prevention
- New skill added: estate-ground-truth-probe
- New skill added: otto-coordinator-rules-2026-06-18
- New skill added: supervised-process-contract
- New cron job: idle-curiosity (every 30m)
- New cron job: otto-dispatch (1-59/5 * * * *)
- New cron job: prospector-daily-generation (0 * * * *)
- New cron job: proving-ground-audit (every 120m)
- New cron job: pytest-orphan-cleanup (every 5m)
- New cron job: queue-curator (*/5 * * * *)
- New cron job: signal-engine-daemon-watchdog (*/5 * * * *)
- Policy not gaining hits: pol-20260618-001 (still at 2)
- Policy not gaining hits: pol-20260618-004 (still at 1)
- Policy not gaining hits: pol-20260618-007 (still at 1)
- Policy not gaining hits: pol-20260618-008 (still at 1)
- New policy: pol-auto-engineering-reliability-20260618 (domain=engineering/reliability)
- Config changed: hash b49492a45853 → 21a3b03fbc35

## Estate Summary
- **Scripts:** 75
- **Skills:** 87
- **Cron jobs:** 21
- **Policies:** 10
- **Config version:** 21a3b03fbc35

## Action Items
- [ ] Review/archive policy: pol-20260618-002 (domain=infra/dispatch)
- [ ] Review/archive policy: pol-20260618-003 (domain=decision-making)
- [ ] Review/archive policy: pol-20260618-006 (domain=engineering/research)
- [ ] Review/archive policy: pol-20260618-010 (domain=engineering/verification)
- [ ] Review/archive policy: pol-20260618-012 (domain=infra/dispatch)
- [ ] Review/archive policy: pol-auto-engineering-reliability-20260618 (domain=engineering/reliability)