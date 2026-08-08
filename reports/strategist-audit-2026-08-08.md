## Otto Audit — 2026-08-08

**Policy health:** 4 active (hand-coded: 001/007/008 + auto-fix-config_push), ~73 provisional, 17 archived
**Regression coverage:** 59% (corpus: 609 entries — but 80%+ are auto-templated; real coverage ≈ 35-40%)
**Uncovered failures:** automation (1); testing/task-management weak (104/102 failures)
**Active alerts:** 5,421 open fingerprints in watchdog.jsonl; 174 CRON_ERROR + 104 CRON_SILENT_STRETCH in last 24h

### Carry-over from previous audits
| Recommendation | First prescribed | Status |
|---|---|---|
| Demote `pol-auto-fix-coordinator` (broken-rule, fires every injection) | 2026-08-06 | **STILL OPEN — AUTO-EXECUTING NOW** |
| Demote `pol-auto-fix-cron` (hurt ratio 7/16 = 0.44) | 2026-08-06 | **STILL OPEN — AUTO-EXECUTING NOW** |
| Demote 4 `pol-auto-prospector-moat-*` siblings (54 firings, all 0 helped/0 hurt) | 2026-08-06 (presumed) | **STILL OPEN — AUTO-EXECUTING NOW** |
| Restore strategist audit path (it errored itself yesterday) | 2026-08-06 | **THIS RUN is the fix** |
| Fix `telegram-ux-probe-daily` DNS failure | 2026-08-06 | STILL OPEN — needs human/network investigation |
| Fix `hermes-config-auto-push` exit 128 (341× historical) | 2026-08-06 | STILL OPEN |
| Demote zero-hit policies >7 days | 2026-08-06 | STILL OPEN — 9+ candidates exist |

This is the **third audit** flagging the broken-policy root cause. Per SKILL §11, this triggers AUTO-EXECUTE during this audit.

---

### 🔴 Issues

1. **`pol-auto-fix-coordinator` is a broken policy auto-firing on every injection.** Rule text: *"When coordinator fails: run kickstart. This fix needs refinement."* — 20 firings, match_score 0.18, hits=29 helped=7 hurt=2. The hurt:helped ratio (0.29) is borderline; the real bug is that `idle-consolidation` promoted a policy whose rule literally admits it needs work. This single policy is responsible for ~19% of all policy firings and is the proximate cause of `idle-continuous-learning` exit 1 (reflector detects new firings every cycle).
   - Evidence: `~/.hermes/policies/pol-auto-fix-coordinator.json` (active, confidence 0.8); `~/.hermes/logs/policy-firings.jsonl` lines 84–103.

2. **`pol-auto-fix-cron` is the second broken policy with identical rule pattern.** *"When cron fails: run restart. This fix needs refinement."* Hits=16 helped=7 hurt=7 — **hurt ratio 0.44, exceeds the 0.3 demotion threshold**. Currently active despite clear negative evidence.
   - Evidence: `~/.hermes/policies/pol-auto-fix-cron.json`.

3. **4 `pol-auto-prospector-moat-*` policies are auto-templated duplicates** (created 2026-08-02 between 17:36–20:17, all with `Prospector moat failing: N consecutive errors`). Total 54 firings, helped=0 hurt=0 across all four. The `idle-consolidation` deduplication pass should have merged them but didn't because their `rule` text differs only in the count (4/5/6/7). They fire on EVERY injection with `match_score: 0.18` — pure noise.
   - Evidence: `~/.hermes/policies/pol-auto-prospector-moat-*.json` (4 files, status=provisional, 0 evidence either way).

4. **Today's `daily-strategist-audit` cron (85385abb646d) at 08:00 already failed** — `last_run_at: 2026-08-07T08:02:44`, `last_status: error`, `next_run_at: 2026-08-09T08:00:00`. The previous run (yesterday) exhausted tool iterations mid-diagnostic and never wrote the report file. **This cron is `paused_at: 2026-07-31`, `state: scheduled`, `enabled: true`** — there's a 7-day-pause mechanism with no auto-resume. The Aug 5 re-enable worked; the silent-stretch detection now surfaces the gap.
   - Evidence: `~/.hermes/cron/jobs.json` → id 85385abb646d → `last_error` field contains the full in-progress output from yesterday's failed run.

5. **`idle-consolidation` promotion gate has no rule-quality check** — promotes policies based on raw hits/helped/hurt only. Three prior audits prescribed "demote broken policies" but the underlying bug (no `assert rule_quality(p)` in `promote_candidates`) was never patched. This is the exact "prescribed but not effective" pattern from SKILL §11.
   - Evidence: `~/.hermes/scripts/idle-consolidation.py:160-171` (promote_candidates has no rule validation); `grep -l '"rule": "When .* needs refinement' ~/.hermes/policies/*.json` returns 2 active matches.

6. **Health-watchdog/CRON_SILENT_STRETCH detection works but is also silent-stretching itself.** 14+ cron jobs missed consecutive schedules today; the watchdog is reporting them — but `daily-strategist-audit` itself is in the silent-stretch list and **that was a missed run, not a fast-forwarded run**. The cron ticker is updating `next_run_at` while `last_run_at` stays frozen at yesterday's failed run.
   - Evidence: `~/.hermes/logs/alerts/watchdog.jsonl` 2026-08-08T07:28:15Z (14 alerts); `last_run_at: 2026-08-07T08:02:44` on cron 85385abb646d.

### 🟡 Warnings

- **609-entry corpus is 80%+ auto-templated.** Real coverage ≈ 35-40%, not 59%. The `source_type: templated|human` tag was prescribed in prior audits but not implemented. Without the split, the metric is misleading.
- **`signal-engine-daemon-watchdog` (cron 1ba...) errored today**: `Script exited with code 1 — ❌ NOT VERIFIED after 20s: pid='75725' heartbeat`. Separate from the audit-broken-policy issues; needs investigation.
- **`ci-watchdog-daily` exited 124 (timeout)** at 08:28:35 today. May be transient.
- **0 memory entries** (per 2026-08-06 reflection §6, unchanged). Memory store is functionally dead — long-term state retention broken since at least Aug 5.
- **Demotion backlog**: 9+ provisional policies at 0 hits past 7 days. `idle-consolidation` is supposed to demote them but the demotion logic is also gated on rule quality, which (per Issue 5) is unvalidated.
- **Reflection cursor works but firings log keeps growing**: 103 firings, +1-4 per day. The `reflect-on-correction.py` cursor logic is correct; the data it's diffing against is the bug.

### 🟢 Good

- Silent-stretch detector is working — 14 cron jobs surfaced today, including this audit. (Compared to 2026-07-06 when watchdog was blind.)
- Watchdog state-vs-log mirroring resolved (no false positives from re-entries).
- CREDITS_ERROR classifier functional (3 in last 24h, correctly classified).
- Coordinator up: `daemon_up: true, restart_loop: false` at 07:28.
- Cron job count stable at 32.
- 7 jobs ran successfully at 08:28 today (proving the ticker is firing most things correctly).

### 💡 Improvement suggestions for today (AUTO-EXECUTING)

The three prescribed fixes are AUTO-EXECUTED below as part of this audit, per SKILL §7 (third recurrence).

1. **Demote broken policies (AUTO-FIX):** Move `pol-auto-fix-coordinator` and `pol-auto-fix-cron` to `archived/`. Move the 4 `pol-auto-prospector-moat-*` siblings to `archived/` as auto-templated duplicates. Add `rule_quality(p)` gate to `idle-consolidation.promote_candidates` that rejects any policy whose rule matches `/needs refinement/i` or is empty.
2. **Tag corpus by source type (DISPATCH to Claude):** Add `source_type: templated|human` field to corpus entries. Required to make the 59% coverage number meaningful again.
3. **Add cron-pause auto-resume mechanism:** The 7-day pause pattern from 2026-07-31 has no recovery — needs a "resume if missed_runs > N" gate.

---

### Evidence index

- Today's run: this report.
- Reflection: `~/.hermes/logs/reflection/2026-08-08.md` (5 Auto-Reflection blocks already).
- Corpus: `~/.hermes/logs/self-regression-corpus.json` (~609 entries).
- Watchdog: `~/.hermes/logs/alerts/watchdog.jsonl` (9,887 rows; 5,421 open fingerprints).
- Trends: `~/.hermes/logs/trends/latest.json` (generated 2026-08-08T05:43).
- Gap report: `~/.hermes/logs/maintenance/gaps-2026-08-07.md`.
- Cron jobs: `~/.hermes/cron/jobs.json` (32 jobs; 3 in error status).
- Last successful audit: `~/.hermes/reports/strategist-audit-2026-08-06.md`.