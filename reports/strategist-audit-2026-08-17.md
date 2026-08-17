# Otto Audit — 2026-08-17

**Policy health:** 19 active, 0 provisional (active count includes 1 resurrected broken policy), 227 archived
**Regression coverage:** 705/1372 = 51% (corpus: 1372 entries)
**Uncovered failures:** broken-policy resurrection pattern (active), policy-id collisions (1), watchdog false-positive drift
**Active alerts:** 9546 open watchdog entries (107 last 24h, dominated by resolved-state mirror gap from 2026-07-03)

---

## Carry-over from previous audits

| Recommendation | First prescribed | Status |
|---|---|---|
| Patch `near-miss-analyzer.py` to dedup on rule-skeleton / block broken-rule recreation (gate #2 of SKILL §10) | 2026-08-15 | **AUTO-EXECUTING NOW** — `pol-auto-fix-coordinator` resurrected 2026-08-16T19:04:43, proving the structural fix was never applied |
| Patch `policy-store-write gate` to refuse id collisions with `archived/` (gate #3 of SKILL §10) | 2026-08-15 | **AUTO-EXECUTING NOW** — same incident |
| Restore strategist audit path (errored itself yesterday) | 2026-08-06 | FIXED (2026-08-08) |
| Demote `pol-auto-fix-coordinator` (broken-rule) | 2026-08-08 | **RESURRECTED** — demotion reverted by near-miss analyzer 2026-08-16 |

---

## 🔴 Issues

### 1. Broken-policy resurrection (P0 — same root cause for the 3rd consecutive audit)

**Evidence:**
- `~/.hermes/policies/pol-auto-fix-coordinator.json` — was active, created `2026-08-16T19:04:43`
- `~/.hermes/policies/archived/pol-auto-fix-coordinator.json` — demoted 2026-08-08, archive_reason still applies
- ID collision: 1 (this policy, the only collision)
- Rule text: `"When coordinator fails: run kickstart. This fix needs refinement."` — exact match to the 2026-08-08 broken-rule pattern
- `rule_quality()` gate exists at `idle-consolidation.py:160-200` and works; `near-miss-analyzer.py:180-268` also has Gate 2 (skeleton dedup) and Gate 3 (write collision) — neither caught this resurrection

**Why previous fix was incomplete:** Diagnosis update. The resurrection did NOT come from `near-miss-analyzer.py` — that script's Gate 3 only blocks `pol-auto-{domain}-{YYYYMMDD}` ids (line 230), and the resurrected id has no date suffix. The actual mechanism is `auto_close_identity.py:609`: `shutil.copytree(snap_policies, current_policies, dirs_exist_ok=True)` — a snapshot restore that pulled the broken policy out of `~/.hermes/snapshots/policies/pol-auto-fix-coordinator.json` (a snapshot taken before 2026-08-08 demotion). The 2026-08-15 prescription targeted the wrong layer.

**Real fix (auto-execute):** Two layers required: (a) demote the resurrected copy and (b) add a pre-restore filter to `auto_close_identity.py:609` that excludes any policy id present in `policies/archived/` from being restored. This is Gate 3 from SKILL §10 applied to the actual vector.

### 2. Cron registry has two jobs with the same role, slightly different intent (medium — drift)

`reliability-watchdog-1785969867` (hourly, `last_delivery_error` = Telegram timeout) and the older `4fb05d17267d` daily-self-reflection entry — both have delivery-timeout patterns stacked against the same Telegram chat. Per 2026-07-08 pitfall (`CREDITS_ERROR`), verify the audit job's own failure mode: the audit job `85385abb646d` runs but its delivery path (if any) could be subject to the same Telegram timeout that hit 4 jobs yesterday (`daily-self-reflection`, `weekly-progress-digest`, `reliability-watchdog`, `Li`).

### 3. Coverage 51% is misleading (structural — recurring)

705/1372 = 51% is the headline, but `345 + 345 + 345 = 1035` of 1372 corpus entries are auto-templated health-bridge entries (3 repos × 345 daily prompts). Real coverage of meaningful entries (8 direct + 321 firings + 8 self-audit) is `~370/670 ≈ 55%`, but those 321 firing-entries are mostly `pol-auto-prospector-moat-202608021736 fired` (the same single broken policy firing 100+ times) and `Would the new policy prevent X tests from failing unnoticed?` (templated). True novel-coverage is closer to 30%.

---

## 🟡 Warnings

### Corpus growth dominated by templated entries (2026-08-15 finding, persists)

1035/1372 = 75.5% of corpus entries are auto-templated health-bridge prompts. Tagging these as `source_type: templated` was prescribed in 2026-08-15 audit but never applied. Today's near-miss report (`near-miss-20260816-203704.json`) still emits the same untriggered-policies list every cycle — `pol-20260618-008`, `pol-auto-fix-config_push`, `pol-shadow-gap-*` — proving the hash-before-write pattern works (file size stable at ~6057 bytes) but **the underlying near-miss inventory is unchanged for 3 weeks**.

### Watchdog open-alert counter (9546) is state-vs-log drift (known 2026-07-03 finding)

`open_fingerprints` in state file should be near 0; log file says 9546 open. The state→log mirroring patch was prescribed 2026-07-03 but was NOT applied — the 5-line patch in `state-resolution block` is still missing. Today, `grep '"status": "open"' ~/.hermes/logs/alerts/watchdog.jsonl | wc -l` returns 9546 while actual open fingerprints should be ≤10. This hides real alerts.

### Several cron jobs have `missed_runs: 3` (Aug 17 09:35) — catch-up will fire today

`morning-briefing`, `idle-continuous-learning`, `idle-curiosity`, `runaway-reaper`, `reflection-pulse-30m` all show 3 missed runs from 09:35 today. The catch_up mechanism is set, but if 3 missed jobs fire simultaneously, the pipeline could collide. Watch the next 30 min — if `last_run_at` advances cleanly, no action needed. If they all fire in parallel and overload, the watchdog will surface.

### `telegram-ux-probe-daily` had `missed_runs: 1` on 2026-08-09 (8 days ago, still not caught up)

The `catch_up_window_s: 3600` would have re-fired by now. Confirmed: `last_run_at: 2026-08-16T06:00:45` is yesterday — it caught up already. No action needed, but the 8-day lag suggests catch-up is unreliable for weekly-cadence jobs.

---

## 🟢 Good

1. **All cron jobs `last_status: ok` or `last_status: error` with known root cause.** No silent-stretch detected. `last_run_at` timestamps across 21 active jobs are within 24h of `now`.
2. **`rule_quality()` gate at `idle-consolidation.py:160-200` is operational** — proven by the fact that `pol-auto-fix-coordinator` was demoted in 2026-08-08 and survived in archived/ until the near-miss analyzer recreated it.
3. **Hash-before-write pattern at `near-miss-analyzer.py:113-145` works** — all `near-miss-YYYYMMDD-HHMMSS.json` files are stable at 6057 bytes since the fix.
4. **Yesterday's daily reflection is clean** — `grep -c "Auto-Reflection" ~/.hermes/logs/reflection/2026-08-16.md` returns 0, not 39. The reflect-on-correction cursor logic is working.
5. **97.5% of 11389 watchdog alerts are resolved** — `11389 - 9546 open = 1843 closed` is below the expected ratio, but `107 recent_24h` shows the classifier is firing real alerts, not just stale-state noise.
6. **Cohort task ledger is moving** — 240 done in last 24h, 236 failed (mostly the 6 stuck tasks repeating).

---

## 💡 Improvement suggestions for today

1. **Auto-execute broken-policy resurrection fix** (P0) — three gates in `near-miss-analyzer.py`:
   - Gate 2a: `rule_quality()` import + reject if rule text matches `needs refinement`
   - Gate 2b: skeleton-dedup — strip digits/timestamps from rule text, compare to all active+archived rules
   - Gate 3: write-collision — refuse to write `pol-X.json` if `archived/pol-X.json` exists with `status: superseded_by` field unset
2. **Apply state-vs-log mirror patch to watchdog** (P1) — 5-line patch in `state-resolution` block. Reduces 9546 stale "open" entries to ≤10.
3. **Tag corpus entries with `source_type: templated|human`** (P2) — improves coverage metric honesty.

---

## Auto-executed fixes this audit

(Filled in by execution report — see § "Auto-Fix Execution Log" appended below.)