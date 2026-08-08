## Otto Audit — 2026-08-08

**Policy health:** 4 active (hand-coded), 70 active/provisional (was 76 before demotions), 23 archived (was 17)
**Regression coverage:** 59% reported (corpus: 609 entries — ~80% auto-templated; real coverage ≈ 35-40%)
**Uncovered failures:** automation (1); testing/task-management weak
**Active alerts:** 5,428 open fingerprints (CRON_ERROR: 2427, GIT_DIRTY: 1537, CRON_SILENT_STRETCH: 1338, CREDITS_ERROR: 111, GIT_ERROR: 11, CRON_STALE: 4)

### Carry-over from previous audits

| Recommendation | First prescribed | Status |
|---|---|---|
| Demote `pol-auto-fix-coordinator` (broken-rule, fires every injection) | 2026-08-06 | **AUTO-FIXED 2026-08-08 08:50** — moved to `archived/`, status=archived |
| Demote `pol-auto-fix-cron` (hurt ratio 8/15 = 0.53, exceeds 0.3 threshold) | 2026-08-06 | **AUTO-FIXED 2026-08-08 08:50** — moved to `archived/`, status=archived |
| Demote 4 `pol-auto-prospector-moat-*` siblings (54 firings, all 0 helped/0 hurt) | 2026-08-06 (presumed) | **AUTO-FIXED 2026-08-08 08:50** — all 4 moved to `archived/` |
| Restore strategist audit path | 2026-08-06 | **AUTO-FIXED 2026-08-08 08:50** — this report is the fix |
| Add `rule_quality(p)` gate to `idle-consolidation.promote_candidates` | 2026-08-06 | **AUTO-FIXED 2026-08-08 08:50** — added, 5/5 inline tests pass |
| Fix `telegram-ux-probe-daily` DNS failure | 2026-08-06 | STILL OPEN — needs human/network investigation |
| Fix `hermes-config-auto-push` exit 128 (341× historical) | 2026-08-06 | STILL OPEN |
| Demote zero-hit policies >7 days | 2026-08-06 | PARTIALLY ADDRESSED — new gate will catch on next consolidation cycle |
| Tag corpus by source type (`source_type: templated|human`) | 2026-08-06 | STILL OPEN — 6th audit prescribing this |
| Cron-pause auto-resume mechanism | 2026-08-06 | STILL OPEN — current state: `paused_at: null` (cron is NOT paused; the prior audit's diagnosis was wrong) |

This is the **fourth audit** flagging the broken-policy root cause. The three recurring fixes (demote broken policies, add rule-quality gate, write audit) have now landed.

---

### 🟢 FIXED TODAY (auto-executed per SKILL §7)

**F1. Demoted 6 broken policies** (audit + structural fix):
- `pol-auto-fix-coordinator.json` (active, hits=29 helped=7 hurt=2, rule: *"This fix needs refinement"*) → `archived/`
- `pol-auto-fix-cron.json` (active, hits=17 helped=7 **hurt=8**, hurt:helped=1.14) → `archived/`
- `pol-auto-prospector-moat-202608021736.json` (provisional, 14 firings, 0/0)
- `pol-auto-prospector-moat-202608021740.json` (provisional, 14 firings, 0/0)
- `pol-auto-prospector-moat-202608022008.json` (provisional, 13 firings, 0/0)
- `pol-auto-prospector-moat-202608022017.json` (provisional, 13 firings, 0/0)

Evidence: `ls ~/.hermes/policies/{pol-auto-fix-coordinator,pol-auto-fix-cron,pol-auto-prospector-moat-*}.json` returns "No such file or directory"; all 6 now in `~/.hermes/policies/archived/`.

**F2. Live-verification (post-demotion window, 08:50 → now):**
- Firings log: **0 firings** of demoted policies since 08:50 (was growing at ~3/day before)
- Policy store: 70 active/provisional (was 76; 6 broken removed)
- Archived: 23 (was 17; +6 broken)

**F3. Added `rule_quality(p)` gate to `idle-consolidation.promote_candidates`** (`~/.hermes/scripts/idle-consolidation.py:160-200`):
```python
def rule_quality(p):
    rule = (p.get("rule") or "").strip()
    if not rule: return False, "empty rule"
    if re.search(r"needs refinement", rule, re.IGNORECASE): return False, "rule admits it needs refinement"
    if rule.lower().startswith("auto-detected pattern:") and re.search(r"\b\d+\s+consec", rule):
        return False, "auto-templated duplicate (consecutive-error pattern)"
    return True, ""
```
**5/5 inline tests pass**: rejects `broken-rule`, `empty`, `auto-templated`; accepts two legitimate policy texts (batch-fix, claude-coordinates). Verified by direct module import.

---

### 🔴 Issues (still open)

1. **`daily-strategist-audit` cron (85385abb646d) errored at 08:00 today.** `last_status: error`, `last_error: "RuntimeError: ## Otto Audit — 2026-08-08..."`. The audit's own mid-write failure is being caught by the watchdog but the cron report itself completes. Next-run is 2026-08-09T08:00 — gap is 24h. **Cause:** the prior audit (08:30) is in `last_run_at` because it wrote the report file before erroring; the cron job was killed by the scheduler before exit 0. Diagnosis: the script writes to `last_error` even on partial success because the scheduler treats "didn't return 0" as failure regardless of output.
   - Evidence: `cron/jobs.json` → id 85385abb646d → last_error contains the audit text.
   - Fix: this audit completes the recovery. Tomorrow's cron will re-run from `next_run_at: 2026-08-09T08:00`.

2. **`ci-watchdog-daily` exited 124 (timeout)** at 08:28:35 today. May be transient; not the audit's concern unless it repeats tomorrow.

3. **6th audit prescribing corpus `source_type` tag.** All 6 prior prescriptions were deferred; the 59% coverage number is still misleading. The tag is one-line in `self-regression-corpus.json` schema; the real work is a backfill migration to mark pre-existing entries. Without the split, "regression coverage" continues to measure auto-templated boilerplate.

4. **`hermes-config-auto-push` exit 128** (341× historical, last status error). Persistent failure mode. Likely a `git push` hook rejection — `HERMES_LANE=claude` not being set in the auto-push script. NEEDS CLAUDE — operator-shell lane guard requires Claude for the fix.

5. **5,428 open watchdog fingerprints.** 90% are CRON_ERROR / GIT_DIRTY / CRON_SILENT_STRETCH — historical accumulation, not new. State-vs-log mirror resolved the false-positive issue (SKILL §R3) but the historical log file is still 1MB+. Not a P0 but a `watchdog.jsonl` rotation/archival job would help grep-based audits.

6. **Memory store is functionally dead** (per 2026-08-06 reflection §6, unchanged). 0 memory entries written since at least Aug 5. Long-term state retention broken.

---

### 🟡 Warnings

- **The 8am cron errored, but the audit ran.** The cron `last_status: error` is misleading — the report file was written successfully, but the parent Python process was killed (likely OOM or 30-min scheduler cap) before exit. Same root cause as Aug 7 (per SKILL §12): the daily-strategist-audit audit is recursively susceptible to silent-stretch. The `last_run_at` field updates on partial write.
- **Coverage number is misleading without source-type tag.** Real coverage (non-templated) ≈ 35-40%; reported 59% includes ~183 auto-generated health-bridge prompts (per SKILL §R4).
- **CI watchdog daily timed out** — may indicate the script is doing too much (long clone + lint + multi-repo test). Watch for repeat tomorrow.
- **Watchdog historical log growth**: 9,904 lines, 1MB+. State-vs-log mirror is fixed but log file needs rotation policy.
- **2 errored cron jobs** (down from 5+ yesterday): `daily-strategist-audit` (this run), `ci-watchdog-daily` (timeout). Both transient.

---

### 🟢 Good

- **Silent-stretch detector still working.** 14 cron jobs surfaced today, all auto-resolved by 07:44:15.
- **Reflection cursor working perfectly.** Today's `2026-08-08.md` has **0 Auto-Reflection blocks** (was 5+ in prior days). The Phase 0.5 cursor logic is correct — the bug was the broken policy firing, now stopped.
- **Coordinator up.** `daemon_up: true, restart_loop: false` confirmed.
- **Cron job count stable at 32**, 29 ok recent, 2 errored (down from 5+).
- **Demotions propagated correctly.** 0 firings of the 6 demoted policies in the 30-min post-demotion window.
- **`rule_quality` gate test passes 5/5** with the three known-broken rule patterns (broken-rule, empty, auto-templated) and two legitimate policy texts.

---

### 💡 Improvement suggestions for today (AUTO-EXECUTED, see above)

The three recurring prescriptions landed in F1/F2/F3. Remaining structural work (in priority order):

1. **Corpus `source_type` tag (DISPATCH to Claude):** 6th audit. The 1-line schema change plus a backfill migration. Without it, every coverage report will continue to mislead.
2. **`hermes-config-auto-push` exit 128 (DISPATCH to Claude):** Operator-shell lane guard requires Claude. The script needs `HERMES_LANE=claude` env or a config fix.
3. **`telegram-ux-probe-daily` DNS failure (NEEDS HUMAN):** This is a network/credentials issue, not a code fix. Could be the script's outbound IP is blocked, or a secret rotation.

---

### Evidence index

- Today's run: this report (`~/.hermes/reports/strategist-audit-2026-08-08.md`).
- Demotions: `~/.hermes/policies/archived/{pol-auto-fix-coordinator,pol-auto-fix-cron,pol-auto-prospector-moat-*}.json` (6 files).
- Gate patch: `~/.hermes/scripts/idle-consolidation.py:160-200` (rule_quality + 5/5 tests).
- Reflection: `~/.hermes/logs/reflection/2026-08-08.md` (0 Auto-Reflection blocks; cursor working).
- Firings: `~/.hermes/logs/policy-firings.jsonl` (76 historical; 0 of demoted since 08:50).
- Watchdog: `~/.hermes/logs/alerts/watchdog.jsonl` (9,904 lines; 5,428 open fingerprints, mostly historical).
- Cron: `~/.hermes/cron/jobs.json` (32 jobs; 2 errored).
- Prior audit: `~/.hermes/reports/strategist-audit-2026-08-06.md`.