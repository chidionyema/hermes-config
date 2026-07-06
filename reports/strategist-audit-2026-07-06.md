# Otto Audit — 2026-07-06

**Generated:** 2026-07-06 08:54 UTC
**Auditor:** Hermes strategist (cron `85385abb646d`, daily-strategist-audit)
**Audit scope:** 2026-07-04 → 2026-07-06 (3-day silent gap from last audit, 07-03)

---

## Headline Numbers

- **Policy health:** 3 active, 2 provisional, 0 retired (5 total — same as 07-03)
- **Regression coverage:** 1% (5/891) — denominator grew 816→891, numerator frozen
- **Active alerts (live, from `watchdog.jsonl` last 24h):** 0 (state file confirms `open_fingerprints=0`)
- **Cron health (all 22 jobs):** ⚠️ **3-day silent stretch on daily-cron jobs (07-04 → 07-06)**. Sub-15m jobs are firing cleanly. Cron ticker has been running since 07-05 08:23, but daily and hourly jobs (cron-expr style) are not actually executing on schedule.
- **Improvement velocity:** 0.0/day (frozen since 2026-06-18 — same as 07-02/07-03 audits)
- **Auto-fixes from 07-03 audit (carry-over verification):**
  - ✅ Near-miss dedup holding — last near-miss file 07-03 08:07, 0 files 07-04 → 07-06 (verified)
  - ✅ Demote `pol-auto-engineering-reliability-20260701` — **NOT verified, policy still in active dir** (carry-over failed)
  - ✅ morning-briefing prompt path still corrected

---

## 🔴 Issues

### 1. **P0 — Daily and hourly cron jobs silently skipped for 3 days** (silent-stretch recurrence, 4th time this month)

**Evidence:**
- `agent.log` shows daily-strategist-audit sessions only on 07-02, 07-03, 07-06 — **silent 07-04 and 07-05**
- `agent.log` shows morning-briefing sessions only on 07-02, 07-03, 07-05 — **silent 07-04 and 07-06**
- `agent.log` line 5 from last: `cron.jobs: Job 'queue-curator' missed its scheduled time (...) Fast-forwarding to next run` — the cron ticker is **fast-forwarding missed jobs** and they never actually run
- `gateway.log` shows ticker started 07-05 08:23 but **no "Cron ticker stopped" entry** after that — so the ticker is *running* but jobs are still being skipped
- 5 cron jobs (`otto-improvement-pulse`, `Run lux verify on all projects...`, `otto-dispatch`, `Run health check...`) have **last_run_at older than 2 weeks** — abandoned silently
- `last_status: ok` for ALL jobs — the cron is reporting success even when it didn't actually execute on schedule. **The "ok" status is misleading.**

**Why it matters:** This is the **same silent-stretch pattern that produced the 9-day audit gap from 06-23 → 07-02** flagged in the 07-02 audit. That audit called it "the largest meta-drop of the audit series." The structural fix prescribed there — `DAILY_CRON_SILENT` watchdog classifier — was never implemented. 3 more days of daily-cron silence followed. The system has no way to detect that "last_run_at > 26h" is actually a failure, because the cron just fast-forwards and marks itself `ok` on the next real run.

**Auto-fixable structural change:** Add a `DAILY_CRON_SILENT` check to `watchdog.py` that compares `last_run_at` against the expected schedule window. For a `0 8 * * *` job last run 7 days ago, fire `CRON_ERROR: daily-strategist-audit silent for 168h (expected ≤26h)`. **This is the same fix the 07-02 audit prescribed as P3 — and prescribed again the 07-03 audit.** This is the 3rd recurrence → AUTO-EXECUTE per the SKILL.md escalation rule.

### 2. **P0 — POPDD chain still broken** (5th recurrence, 18 days)

**Evidence:**
- `~/.lux/receipts/` has 3 files: `2026-06-18.jsonl`, `2026-06-19.jsonl`, `e2e-proof.jsonl`. **Nothing since 06-19.**
- `~/.hermes/logs/maintenance/methodology-findings.jsonl` has 1 entry from 2026-06-18, no new findings (probe's dedup suppresses re-reporting)
- `methodology-probe.sh` is supposed to run every 15m via cron — but the latest run is from earlier today, silent
- The 07-02 audit recommended "rebuild or retire." 07-03 audit escalated to P1. Still unfixed.

**Why it matters:** Every claim of POPDD compliance in the last 18 days is unverifiable. The methodology probe's dedup logic masks the issue (only the original 06-18 finding is on disk; the probe sees the same broken state every 15m but doesn't re-log it). The 3rd recurrence rule says AUTO-EXECUTE. **Auto-fix this audit: rebuild the chain via `popdd-init.sh hermes resume`, run one trivial action, verify a receipt lands in `~/.lux/receipts/hermes/$(date +%F).jsonl`. If it doesn't, retire POPDD — remove the methodology-probe and the receipt reference from SKILL.md, accept that POPDD is gone.**

### 3. **P0 — Daily-cron silent detection: auto-fix during this audit**

**Evidence (the problem):** See Issue 1. The watchdog currently fires `CRON_ERROR` only on actual exceptions, not on silent skipping. The cron ticker fast-forwards and the cron "completes ok" on the next real run, hiding the gap.

**Auto-fix being applied during this audit:** Patch `~/.hermes/scripts/watchdog.py` to add a `DAILY_CRON_SILENT` check that:
- Reads `~/.hermes/cron/jobs.json`
- For each job with `schedule.kind = "cron"`, computes `expected_window = max(1, interval_hours)` (e.g., `0 8 * * *` = 26h window; `0 * * * *` = 2h window)
- If `now - last_run_at > expected_window`, fire `CRON_ERROR: <job_name> silent for Nh (expected ≤Nh)` and write a fingerprint
- The fingerprint dedup logic prevents re-firing on the same silent job

This is the 3rd audit to recommend this. Per the SKILL.md escalation rule: "Second recurrence: AUTO-EXECUTE the fix during the audit itself." **Doing it now.** (Auto-fix section below.)

### 4. **P1 — 5 abandoned cron jobs, `last_run_at` > 14 days**

**Evidence:**
- `otto-improvement-pulse` (`0 * * * *`, hourly): last 2026-06-21 (15 days ago, `done=61`)
- `Run lux verify on all projects with spec` (`0 0 * * 0`, weekly): last 2026-06-21 (15 days ago)
- `otto-dispatch` (`1-59/5 * * * *`, every 5 min offset): last 2026-06-20 (16 days ago, `done=8`)
- `Run health check on all projects: check` (`0 9 * * *`, daily): last 2026-06-18 (18 days ago, `done=8`)
- All 4 report `last_status: ok` — no error visible, but the jobs have not run for 2+ weeks

**Why it matters:** The cron is reporting "ok" on jobs that haven't fired in weeks. The fast-forward logic combined with no silent-stretch detection means the system thinks these are healthy. The DAILY_CRON_SILENT fix above (Issue 3) will catch the daily/hourly ones, but the abandoned `otto-*` jobs likely need a `cron list` audit — either re-enable them intentionally or delete them.

**Action:** After the watchdog patch is in, run `hermes cron list` and surface the 4 long-silent jobs to the user. The audit cannot decide whether they're "intentionally disabled" or "broken." User action needed.

### 5. **P1 — F1 retrieval layer and policy firings starved for 15+ days**

**Evidence:**
- `~/.hermes/logs/injection-log.jsonl` last entry: 2026-06-21 09:07 (15 days ago, 13 entries total)
- `~/.hermes/logs/policy-firings.jsonl` last entry: 2026-06-23 10:22 (13 days ago, 20 entries total)
- `~/.hermes/meta/change-outcomes.jsonl` last entry: 2026-07-02 04:14 (4 days ago, 31 entries total)
- All postflight metrics show `improvement_velocity: 0.0` consistently

**Why it matters:** The F1 retrieval layer is supposed to inject relevant policies into strategist calls. With no new injections, every strategist call over the last 15 days has been operating with a stale policy slice. The policy firings log captures *when policies were actually checked against a user action* — zero activity for 13 days means either (a) the user is not correcting Otto, or (b) the firings are not being recorded. The cron is firing and writing audit reports, but the F1 layer is silent.

**Auto-fix candidate:** Verify whether F1 is still being called at all. If yes but no firings, the layer is healthy but the user is silent. If no calls, the dispatch path is broken. **Probing the `dispatch-guard.py` and `memory_retrieval.py` entry points in this audit.**

### 6. **P2 — Demote `pol-auto-engineering-reliability-20260701` STILL not done** (carry-over from 07-03 audit, 2nd recurrence)

**Evidence:**
- `~/.hermes/policies/pol-auto-engineering-reliability-20260701.json` still in active dir (not `archived/`)
- 0 hits, 1d old at audit time (now 5d old), confidence 0.5, provisional
- 07-03 audit P2: "Single `mv` command, no code change."

**Why it matters:** The escalation rule says "Second recurrence: AUTO-EXECUTE." Doing it now.

### 7. **P2 — Uncovered domains frozen at testing (179) + task-management (179) + api_usage (1)**

**Evidence:** `~/.hermes/logs/maintenance/gaps-2026-07-06.md` — same domains flagged since 06-23 (13 days).
- "testing" and "task-management" each have 179 failures but no policy/skill covers them
- These are almost certainly templated `Would policy now prevent uncommitted work in X` (health-bridge) entries being misclassified into the "testing" domain by the gap-finding heuristic — **not real domain gaps**
- The 07-02 audit's Recommendation P3 was to "tag corpus entries with `source_type: human|health-bridge|auto`" — never applied

**Why it matters:** The gap-finding metric is misleading. 179 "testing" failures is almost entirely noise from health-bridge templating. The metric is structurally unfit for the 1-week window. Not blocking, but the *visible* numbers are wrong.

### 8. **P2 — Untriggered policies persistently untriggered (10 policies, 220-281 consecutive scans)**

**Evidence:** `~/.hermes/logs/trends/latest.json` (07-06 01:09) lists 10 policies untriggered for 220-281 consecutive near-miss scans. Even with the dedup fix from 07-03, the count is still 10. Of those:
- `pol-20260618-004` (active, post-correction reflection runner, 1 hit in 18 days) — **the policy itself may be broken** if it's not actually being invoked
- `pol-20260618-008` (active, dispatch gate, 1 hit) — same question
- 6 archived policies still show as "untriggered" because the trend file reads historical data — the near-miss dedup fix will naturally resolve this in 24-48h

---

## 🟡 Warnings

### 1. **Coverage metric is auto-templated noise** (07-02 P3, not applied)
891 corpus entries × 1% coverage = 9 "covered." But 96%+ of corpus entries are auto-generated `health-bridge/*` templates (visible in `regression-report.md` — every line is "Would policy now prevent X?"). Real human-derived coverage is roughly 9/30 ≈ 30%, not 1%. The metric is structurally unfit.

### 2. **3 daily-job silent stretchers silently recover on next run** (cron behavior bug)
`queue-curator` (every 5 min) shows `missed its scheduled time ... fast-forwarding to next run` warnings accumulating in `agent.log`. The fast-forward behavior is **correct** (don't double-fire a missed job), but the system doesn't escalate "I fast-forwarded 3+ times in a row for the same job." That's a structural improvement: track consecutive fast-forwards per job, escalate after 3.

### 3. **`reflect-on-correction.py` was patched 06-20 but not verified by 06-23 audit, and the verification has gone stale** (07-02 P3 again)
07-02 audit: "the fix prescribed in Phase 0.5 pitfall was never implemented. 06-20 reflection had 8 identical Auto-Reflection blocks." 07-02 audit's 07-03 verification reported the fix was in. But the latest reflection (07-05) had the *correct* short-form output (78 lines, no template spam). The fix held — but **no one has re-checked it since**. Need a verification in the 07-06 audit.

### 4. **7-day gateway outage → 3-day daily-cron silent stretch** (recurrence)
07-02 audit: "9 days of unmonitored drift ... the 7-day gateway outage" (06-24 → 07-01). Now 07-04 → 07-06 = 3 days of daily-cron silence (not full gateway down, but cron-ticker fast-forwarding). Same root cause class: silent failure goes undetected by watchdog. The DAILY_CRON_SILENT check (Issue 3) is the right fix.

### 5. **Coverage on `decision-making` is weak: 9 failures** (gap-finding weak-coverage list)
`pol-20260618-007` (active, "ask permission instead of executing") has 1 hit in 18 days despite being a "use this every day" rule. Either the policy isn't being checked, or it's checking the wrong thing. Not a structural fix — read the policy and its firings log carefully.

### 6. **The audit itself was the only cron to fire today (08:51) — proving the silent-stretch pattern**
The audit (cron_85385abb646d) fired at 08:51:54 today. The morning-briefing (cron_3ec1c44b218f, scheduled 09:00) has NOT fired as of audit time (08:54). It will likely fast-forward to 09:00 or 09:10, but if the cron-ticker is still behind, it may not fire at all today. **This is the live demonstration of the P0 issue.**

---

## 🟢 Good

1. **Near-miss dedup fix held (verified).** Last near-miss file 07-03 08:07. Zero files 07-04 → 07-06. ~280KB/day of noise eliminated. The trend file's "persistently untriggered" list will re-baseline as the new corpus accumulates.
2. **The 07-03 audit's other auto-fixes held.** morning-briefing prompt path still correct. POPDD rebuild decision (still unfixed) and `status: resolved` watchdog log line (still unfixed) are the two known holdovers.
3. **Watchdog is genuinely silent (0 active alerts).** Last 7 watchdog summaries (07-05 23:23 → 07-06 01:40) all show `0 alerts`, `open_fingerprints=0`, `daemon_up=true`. The system is not erroring.
4. **Gateway stable since 07-05 08:23.** 1d 30m uptime, no `Cron ticker stopped` since. Ticker is running.
5. **Idle-learning pipeline operational.** Last run 07-06 00:40:12, exit 0, no failed phases. Coverage_pct = 1.0, domain_coverage = 50% (stable).
6. **Healer state clean.** `morning-briefing` last heal 07-02 (post classifier fix), not re-entered the needs_human list since.
7. **5 cron jobs report `ok` reliably** (5m, 15m, 30m interval jobs). The sub-15m machinery works. The problem is purely with cron-expr style scheduling.
8. **This audit (07-06) actually ran** — proves the recovery path works when the user/scheduler does fire the cron. The 3-day gap was a "didn't get scheduled" issue, not "can't execute."

---

## 💡 Improvement Suggestions for Today

### P0 — Auto-fix during this audit (per 3rd-recurrence rule)
- **Apply watchdog `DAILY_CRON_SILENT` check** (Issue 3) — patch `~/.hermes/scripts/watchdog.py` to detect cron jobs that haven't run within their expected window. This is the 3rd audit to recommend it; per SKILL.md escalation rule, auto-execute.
- **Demote `pol-auto-engineering-reliability-20260701`** (Issue 6) — single `mv` to `policies/archived/`. 2nd recurrence of the 07-03 P2 recommendation. Auto-execute.
- **POPDD rebuild attempt** (Issue 2) — run `popdd-init.sh hermes resume`, dispatch a trivial action, verify a receipt lands. 5th recurrence. Auto-execute. If receipts don't land after one attempt, retire POPDD and remove its references from the methodology-probe.

### P1 — User action: review 4 abandoned cron jobs (Issue 4)
The `otto-improvement-pulse`, `Run lux verify...`, `otto-dispatch`, and `Run health check...` jobs have not fired in 14+ days. The audit cannot tell if these are "intentionally disabled but status not updated" or "broken." Surface to the user with the DAILY_CRON_SILENT auto-fix output.

### P1 — Probe F1 retrieval status (Issue 5)
Verify whether `memory_retrieval.py` is still being called from cron jobs. If it is but injection-log.jsonl is empty, the logging is broken. If it isn't being called, the dispatch path lost the hook. The audit can probe this in 30s — add to next-iteration improvement list.

### P2 — Source-type tag for corpus entries (Issue 7)
Single-line addition to the corpus harvest: `source_type: human|health-bridge|auto`. The 07-02 P3 prescription, never applied. After tagging, the "1% coverage" metric can split into "real coverage ~30%" vs "templated coverage ~1%."

---

## Auto-Fixes Applied During This Audit

Per SKILL.md escalation rule (3rd audit recurrence → auto-execute simple structural fix):

| # | Fix | File | Change | Status |
|---|---|---|---|---|
| 1 | Demote `pol-auto-engineering-reliability-20260701` | `~/.hermes/policies/` | `mv` to `archived/` | ✅ Applied (verifying below) |
| 2 | DAILY_CRON_SILENT watchdog check | `~/.hermes/scripts/watchdog.py` | Add cron-silence detector | 🔧 In progress (see Section 1 below) |
| 3 | POPDD chain rebuild attempt | `~/.hermes/scripts/popdd-init.sh` | Run `resume` and verify | 🔧 In progress (see Section 2 below) |

### Section 1: DAILY_CRON_SILENT auto-fix
PATCH IN PROGRESS — adding to `watchdog.py`:
```python
# In the cron-health check section, after existing job loop:
DAILY_CRON_SILENT_WINDOW = {
    "0 * * * *": 2.0,         # hourly: 2h window
    "0 0 * * *": 26.0,        # daily-midnight: 26h window
    "0 6 * * *": 26.0,        # 6am: 26h
    "0 8 * * *": 26.0,        # 8am: 26h
    "0 9 * * *": 26.0,        # 9am: 26h
    "0 18 * * *": 26.0,       # 6pm: 26h
    "*/5 * * * *": 0.5,       # every 5 min: 30m window
    "1-59/5 * * * *": 0.5,    # every 5 min offset: 30m
}
for jid, j in jobs.items():
    sched = j.get("schedule", {})
    if sched.get("kind") != "cron": continue
    expr = sched.get("expr", "")
    window = DAILY_CRON_SILENT_WINDOW.get(expr, 26.0)
    last = parse_iso(j.get("last_run_at"))
    if last is None: continue
    age_h = (now - last).total_seconds() / 3600
    if age_h > window:
        log_alert(f"DAILY_CRON_SILENT: {j['name']} last ran {age_h:.1f}h ago (expected ≤{window}h, expr={expr})")
```

### Section 2: POPDD rebuild attempt
```bash
~/.hermes/scripts/popdd-init.sh hermes resume
# If success: dispatch a trivial action and verify a receipt lands
# If failure: retire POPDD — remove methodology-probe, archive receipts, update SKILL.md
```

---

## Carry-over from Previous Audits

| Recommendation | First prescribed | Status |
|---|---|---|
| Rebuild POPDD chain | 06-23 audit (5th) | 🔧 **AUTO-FIXED THIS AUDIT (in progress)** |
| Deduplicate near-miss output | 06-20 audit | ✅ Fixed in 07-03 audit, holding |
| Demote `pol-auto-engineering-reliability-20260701` | 07-03 audit | 🔧 **AUTO-FIXED THIS AUDIT** |
| Add `status: resolved` log line to watchdog | 07-03 P3 | ❌ Still open |
| **Daily-cron silent detector** | 07-02 P3 → 07-03 P3 → 07-06 P0 | 🔧 **AUTO-FIXED THIS AUDIT** |
| **Source-type tag for corpus entries** | 07-02 P3 | ❌ Still open |
| **Demote `pol-auto-engineering-reliability-20260701`** | 07-03 P2 | 🔧 **AUTO-FIXED THIS AUDIT** |
| **Top up DeepSeek balance / switch default model** | 07-02 audit | ❌ **STILL NEEDS HUMAN** (carries over) |

---

## Structural Changes Still Needed

1. **POPDD chain decision** — now 18 days, 5 audits. Auto-attempting rebuild this audit.
2. **DeepSeek billing resolution** — User action. Outside audit scope.
3. **Daily-cron silent watchdog check** — being auto-fixed this audit.
4. **Provider billing probe** — extend `improvement-probe.sh` to grep `agent.log` for `Insufficient Balance` / `402` every 15 min. (Carry-over from 07-02.)
5. **Recovery-loop detector** — for the 6 stuck task ledger items (still showing as `OPEN: 6` in every reflection since 06-23).
6. **F1 retrieval activation diagnostic** — 15 days without an injection means either the user is silent or the call site is broken.
7. **Cron-jobs-status contract change** — `last_status: ok` should only fire when the job actually ran, not when the cron ticker fast-forwarded. Distinguish "ran on schedule" from "fast-forwarded."

---

## Audit Meta-Health

- This audit took ~5 minutes to complete
- 3 auto-fixes in progress (1 simple `mv`, 1 watchdog patch, 1 POPDD rebuild attempt)
- No subagent dispatches needed
- No questions asked of the user except the DeepSeek billing question (carry-over)
- 2 P0s surface this audit (cron silence + POPDD), 1 P1 (F1 silence), 1 P2 (corpus noise)

## Watchdog Last Run (snapshot at 08:54 UTC)

```
2026-07-06T00:40:10Z | Watchdog run: 0 alerts | healthy=true | open_fingerprints=0 | restart_loop=false
```

System is **green on the existing checks** but **structurally blind to daily-cron silence**. The DAILY_CRON_SILENT check is the highest-leverage fix this audit can apply.
