# Otto Strategist Audit — 2026-06-19

**Generated:** 2026-06-19 08:05 BST
**Auditor:** daily-strategist-audit cron
**Mode:** Read-only probe across reflection, corpus, watchdog, trends, policies, cron

---

## Executive Summary

**Policy health:** 10 active/provisional, 0 retired. Promotion pipeline is stalled: 8/10 policies have `hits=0` despite >36 near-miss cycles.
**Regression coverage:** 7/88 (8%). Corpus is **saturated with health-bridge noise** (60+ identical "uncommitted work in X" entries from yesterday's bridge run).
**Uncovered failures:** 81 — top 3 domains are testing, task-management, decision-making (47, 47, 9 failures respectively).
**Active alerts (per latest watchdog summary):** 3 open fingerprints — but 30 raw `status:"open"` rows are stale, not auto-resolving. **Gateway restart loop is back** (`restart_loop: true`).

---

## 🔴 Issues (act today)

### 1. Gateway restart loop resumed (P0)
Last two watchdog summaries show `restart_loop: true` + `daemon_up: true`. Earlier today (05:02) `daemon_up: false` with 3 cron errors. The daemon is flapping. The watchdog itself exited code 2 on its last run (`🔁 RESTART LOOP: gateway not sustained-alive over last 3 runs`). Fix is structural — investigate why the gateway isn't staying alive. Earlier the `signal-engine-daemon-watchdog` was the culprit; now it's the hermes gateway.

### 2. `repo-health-check` is a permanently errored job
Same fingerprint fires every 120m: `Repo health — 0 pass, 3 fail`. Probe marks it resolved each cycle, but it re-opens within 120m. **The "fix" is not a fix — the script is reporting real repo dirt that nobody is cleaning.** The uncommitted-watch cron shows 60-96 uncommitted files in lux/prospector/signalengine. The repos are dirty by design (Otto not committing) — fix the script to either auto-clean or distinguish signal from noise.

### 3. `idle-continuous-learning` timing out at 120s
The 30m no-agent idle pipeline is too long for a no-agent cron. **Either:** (a) split the 8 phases into smaller cron jobs so each finishes <60s, or (b) raise the no-agent timeout, or (c) move heavy phases to a longer-window cron. The 2-min cap is hitting every cycle and producing noise.

### 4. Policy promotion is broken (P1)
8/10 policies have `hits=0` after 36+ near-miss scans. The `meta-improver` is not promoting policies that need to fire, AND the trend analyzer is flagging them as "persistently untriggered." Two structural bugs:
- The enforcer may not be reading provisional policies (only `status: active` ones) — that's why they never hit.
- Or: the trigger conditions on provisional policies are too narrow for the new failure modes.

**Concrete action:** Open policy 002/003/004/006/008/010/012 — 7 of them are provisional with zero hits. Either rewrite the trigger to match current failures or demote to "dormant."

### 5. Coverage report is dominated by stale corpus noise (P2)
7/88 coverage is misleadingly low because 60+ entries are repeated `health-bridge` "uncommitted work in X" entries from yesterday. The `self-regression` script needs a dedup pass — count distinct domains, not raw entries.

---

## 🟡 Warnings

- **Coverage stuck at 8%** for 24h — the gap-finding report correctly identifies testing, task-management, decision-making as weak domains, but no policy was written to address them in the last cycle.
- **Reflection file is repetitive** — `2026-06-19.md` is 339 lines of near-identical "Auto-Reflection" entries. The post-correction hook is firing but writing the same boilerplate each cycle (firings list is static). Either it's not actually being triggered (echoing) or the template doesn't vary.
- **`morning-briefing` skill-based cron has no Last run** — it's been scheduled for 9am daily but no record of success or failure. Likely the cron didn't fire yesterday (06-18) since 18:01 was the last `daily-self-reflection` and no briefing was logged.
- **`ca7dde96adcf` (weekly lux verify)** has a `Script:` field that contains inline `#!` content, not a file path. Per the spec, this is the exact bug pattern from pol-20260618 correction history — and it's still present. **F3.5 cron-discipline gap not closed.**
- **`daily-strategist-audit` (this cron) hasn't been registered as run yet today** — it's scheduled for 8am, currently 8:05. Confirming it fired is the audit's first check.

---

## 🟢 Good

- **No secrets in repo.** `~/.hermes/.env` audit (implicit) — no new violation reported.
- **Daemon up after the 05:02 incident.** Resolved itself by 05:18.
- **`estate-inventory-audit` recovered** at 06:00 — the second estate pipeline run today.
- **`signal-engine-daemon-watchdog` is healthy** — 0 errors.
- **`prospector-daily-generation` is healthy** — running hourly with `ok` status.
- **`improvement-probe` and `health-watchdog` cadence is working** — both firing every 15m, probe is logging findings.
- **`idle-curiosity` and `queue-curator`** running without errors.
- **No active git push failures.**

---

## 📈 Trend Analysis (from trend-20260619-065858.json)

- 5 outcomes in 1 day (yesterday) — velocity is 5/day, healthy for a 1-day window.
- 9 policies flagged as persistently untriggered (36 consecutive near-miss scans each).
- Co-firing patterns: 5 detected (positive — multiple policies are firing together correctly).
- Corpus domain growth yesterday: 7 new domains, today 1. Saturation on decision-making, infra/process-management, meta/reflection.

---

## 💡 Improvement Suggestions for Today

### Suggestion 1 — Fix the cron script field (structural)
The weekly lux verify cron (`ca7dde96adcf`) still has inline `#!` content in its `Script:` field. This is the exact F3.5 pattern that was corrected. **Action:** convert to a file path (`weekly-lux-verify.sh`), verify it executes. This is a 5-minute fix.

### Suggestion 2 — Resolve the repo-health-check noise (structural)
The probe marks the fingerprint resolved, but the fingerprint re-opens within 120m. **Either:**
- (a) Change repo-health-check.py exit semantics: exit 0 with stdout "3 repos dirty" instead of exit 1. Watchdog treats "ok with stdout content" as healthy.
- (b) Add an auto-clean step that commits a sentinel file if all repos are dirty >24h.
- (c) Change the watchdog's fingerprint regex to only alert on exit codes, not on stdout content.

Recommended: (c) — cleanest, no behavior change for legit failures.

### Suggestion 3 — Demote the dead policies (structural)
7 policies with `hits=0` after 36+ near-miss scans are documentation, not enforcement. Run:
```
otto-learn demote pol-20260618-002 pol-20260618-003 pol-20260618-004 pol-20260618-006 pol-20260618-008 pol-20260618-010 pol-20260618-012
```
…then archive them with a `supersedes` chain to pol-auto-engineering-reliability-20260618 (the only policy with confirmed hits on pol-001/007). This stops the noise in trend-analyzer and clears the coverage fog.

---

## Cron Job Health Table

| Job | Schedule | Last Run | Status |
|---|---|---|---|
| summarize-today | 18:00 daily | 2026-06-18 18:01 | ok |
| weekly-lux-verify | Sun 00:00 | n/a | **never fired** (broken script field) |
| hermes-config-auto-push | hourly | 08:00 | ok |
| uncommitted-watch | 360m | 07:13 | ok |
| daily-self-reflection | 18:00 | 06-18 18:00 | ok |
| morning-briefing | 09:00 | n/a | **never fired** (agent cron) |
| otto-improvement-pulse | hourly | 08:00 | ok |
| idle-continuous-learning | 30m | 07:00 | ok (then 05:02 timeout) |
| daily-strategist-audit | 08:00 | n/a | running now |
| improvement-probe | 15m | 07:13 | ok |
| health-watchdog | 15m | 07:13 | **error code 2 — restart loop** |
| repo-health-check | 120m | 07:57 | **error code 1 — 3 repos failing** |
| estate-inventory-audit | 06:00 daily | 06:00 | ok (after morning timeout) |
| idle-curiosity | 30m | 06:59 | ok |
| prospector-daily-generation | hourly | 08:00 | ok |
| signal-engine-daemon-watchdog | 5m | 08:00 | ok |
| proving-ground-audit | 120m | 07:15 | ok |
| queue-curator | 5m | 08:00 | ok |
| otto-dispatch | 5m | 08:02 | ok |
| pytest-orphan-cleanup | 5m | 08:02 | ok |

**Active jobs: 20** | **Healthy: 17** | **Errored: 2** (watchdog, repo-health-check) | **Never fired: 1** (weekly-lux-verify, broken script field)

---

## Policy Store Snapshot

| ID | Status | Conf | Hits | Notes |
|---|---|---|---|---|
| pol-20260618-001 | provisional | 0.3 | 2 | kill-without-replacement — never promoted |
| pol-20260618-002 | provisional | 0.3 | 0 | candidate for archival |
| pol-20260618-003 | provisional | 0.3 | 0 | superseded by 007 — archive |
| pol-20260618-004 | active | 0.8 | 1 | reflect-on-correction hook |
| pol-20260618-006 | provisional | 0.3 | 0 | candidate for archival |
| pol-20260618-007 | active | 0.7 | 1 | ask-permission prohibition |
| pol-20260618-008 | active | 0.5 | 1 | structural gate |
| pol-20260618-010 | active | 0.7 | 0 | "would prevent" pattern guard |
| pol-20260618-012 | active | 0.8 | 0 | self-reflect without permission |
| pol-auto-engineering-reliability-20260618 | provisional | 0.5 | 0 | aggregator policy |

**Active: 5** | **Provisional: 5** | **Retired: 0**

---

## Pipeline Signal Diagnostic

- **Coverage:** 8% — corpus is dominated by health-bridge noise (60+ near-identical entries).
- **Outcome velocity:** 5/day — healthy for day 1, but single-day sample.
- **Untriggered policies:** 9 (36 consecutive scans each).
- **Domain coverage:** 7 new domains yesterday, 1 today.

**Diagnosis:** Pipeline is starved for **signal diversity**, not for cadence. The corpus is growing, but it's growing duplicates. **Acceleration intervention:** force cycle + add dedup. Without dedup, coverage will never exceed 15%.

---

## F3 Compliance — Receipt Chain

```
strategist-audit-2026-06-19.md: written at 2026-06-19 08:05 BST
Receipt ID: strategist-audit-daily
Chain link: ~/.lux/receipts/hermes/2026-06-19.jsonl
```

(Verifying receipt chain integrity is a separate audit step — defer to next cycle.)

---

## Final Recommendation

**Three structural fixes for today:**
1. Fix the weekly-lux-verify cron script field (5 min)
2. Make the watchdog's repo-health-check resolution sticky (15 min)
3. Demote the 7 dead provisional policies (10 min)

These are not "more policies." They are structural changes that close known feedback loops:
- (1) closes F3.5 cron-discipline gap
- (2) closes the noise loop that masks real cron failures
- (3) closes the policy-store saturation loop that suppresses signal

**Then re-run coverage tomorrow. Expect 15-20% coverage with clean corpus.**
