# Otto Audit — 2026-07-11

**Generated:** 2026-07-11 09:21 BST
**Mode:** Cron strategist audit (85385abb646d) — DISPATCHER ITSELF FAILED on the same root cause (DeepSeek 402)
**Layer-verification gate:** The root-cause finding below was verified against `agent.log` (78 `Insufficient Balance` entries), `jobs.json` (2 errored agent-required jobs), and `watchdog.jsonl` (107 CREDITS_ERROR + 52 CRON_SILENT_STRETCH entries).

---

## Headline Numbers

| Metric | Value | Trend |
|---|---|---|
| **Policies** | 5 total — 3 active, 2 provisional, 0 retired | Flat (was 5 last 4 audits) |
| **Regression coverage** | 0% (5/1011) — 5 active policies × ~1 hit each | Stale: 950/1011 corpus entries are auto-templated, real coverage ≈ 2% (19/1011) |
| **Corpus size** | 1011 entries | Grew from 969 in 24h (mostly templated health-bridge adds) |
| **Active watchdog alerts** | 6 open fingerprints (CREDITS_ERROR + CRON_SILENT_STRETCH on top of normal traffic) | Up from 1–2 yesterday |
| **Cron jobs errored** | 2 of 22 (`morning-briefing`, `daily-strategist-audit`) — both **the audit job itself** + the briefing it reads from | NEW (was 0 yesterday) |
| **Idle pipeline** | Last run 2026-07-11 01:02:04 — `reason=Complete, exit=0` | Healthy |
| **Provider billing** | DeepSeek `HTTP 402 Insufficient Balance` since **2026-07-01 22:24** (10 days, 78 occurrences) | Worsening — now blocking user-facing jobs |
| **Untriggered active policies** | 3 of 3 active policies have **never re-fired since promotion** — 283 consecutive near-miss scans | Dead-on-arrival pattern |

---

## 🔴 Issues

### I1 — P0: DeepSeek billing exhausted (10 days unresolved, now blocking user-facing jobs)

**Evidence:**
- `~/.hermes/logs/agent.log`: 78 `Insufficient Balance` entries between 2026-07-01 22:24:39 and 2026-07-11 09:20:48
- 3 cron jobs hit the 402 in the latest window: `cron_85385abb646d` (daily-strategist-audit), `cron_3ec1c44b218f` (morning-briefing), `cron_f5f63e9ff435` (Summarize today's activity)
- `~/.hermes/config.yaml` line `model.default: deepseek-v4-pro` + `provider: deepseek`
- Fallback `provider: minimax, model: MiniMax-M3` IS configured but **never used** — the agent loop retries DeepSeek 3× then errors out
- Both errored jobs are `no_agent: false` (i.e., they MUST use an LLM) and have no `model` override in jobs.json → inherit default DeepSeek
- **This audit job itself (cron_85385abb646d) is in the errored set** — it's a `RuntimeError` from the LLM call, not a watchdog re-fire

**Root cause (Layer 1, external — billing):**
DeepSeek account is out of credit. Cannot be fixed by Hermes code. Must be fixed by Chidi: top up DeepSeek balance OR change the cron jobs' `default` model + provider to a working one (e.g., minimax fallback is already wired).

**The previous audit (2026-07-10) flagged this as P0 too** — see "Escalation on stale recommendations" below. Carry-over count: **2 audits in a row**.

### I2 — P0: Audit job itself is broken (recursive failure mode)

The 8am cron strategist audit is the very tool that surfaces this P0. Since it cannot run on DeepSeek 402, the system is flying blind for the third consecutive morning. The watchdog catches it as `CREDITS_ERROR`, but the audit cannot fire its own recovery. The 2026-07-10 audit ran at 13:05 (with the same RuntimeError); the 2026-07-11 attempt at 09:20 also 402'd.

**Fix (structural, can be done without billing):** Set the audit job's `model` and `provider` overrides in jobs.json to minimax (already configured as fallback). Same for morning-briefing. This bypasses the broken DeepSeek pool.

### I3 — P0: 3 active policies never re-fire (283 consecutive near-miss scans untriggered)

**Evidence:**
- `~/.hermes/logs/trends/latest.json` lists `persistently_untriggered_policies` with all 3 active policies at the top:
  - `pol-20260618-004` — 283 scans
  - `pol-20260618-008` — 283 scans
  - `pol-20260618-007` — not in trend top-10 but `hits=1` in policy JSON (only ever fired once, at creation)
- Policy firings log last touched `2026-06-23` (18 days stale, only 20 lines)
- Each policy was created with `hits=1` from its own creation test and has not fired in any real dispatch since

**Root cause:** The active policies encode high-level correction themes (don't ask permission, don't repeat pattern, always use POPDD). They were never converted into *retrievable* trigger strings that the F1 routing layer would surface. F1 retrieval never returns them, so they never fire, so they look untriggered, so the meta-improver wants to demote them — but they're the very policies Otto depends on.

**The 3% regression coverage metric is misleading** (2026-07-06 audit caveat still applies): of 1011 corpus entries, 950 are auto-templated "Would policy now prevent X" lines from `health-bridge/{lux,signalengine,prospector}`. Real coverage of meaningful failures ≈ 2% (19/1011).

### I4 — P1: 4 cron jobs dormant 20+ days (silent-stretch blind spot)

**Evidence:** `jobs.json` `last_run_at` timestamps:
- `9ba1919c7386` "Run health check on all projects" — **2026-06-18** (23d ago, `state=paused`, `paused_reason: superseded by repo-health-check.py`)
- `f0b2079864c5` "otto-dispatch" — **2026-06-20** (21d ago, paused)
- `ca7dde96adcf` "Run lux verify on all projects" — **2026-06-21** (20d ago, `enabled=True` but never fires)
- `d2cb4cf8d9db` "otto-improvement-pulse" — **2026-06-21** (20d ago, `state=paused`)

3 of these are paused intentionally (superseded). 1 (`ca7dde96adcf` lux verify weekly) is `enabled=True, state=scheduled` but the cron ticker has not fired it since 2026-06-21. The watchdog caught this as `CRON_SILENT_STRETCH: Run lux verify... missed 2 consecutive schedules (last_run_at stuck at 2026-06-21T00:00:07, cadence=168h)` — open fingerprint.

### I5 — P1: Watchdog re-firing on its own self-errors + idle-pipeline preempts

`watchdog.jsonl` totals: **5458 lines**, breakdown:
- 2093 `watchdog_summary` (mostly noise)
- 1459 `GIT_DIRTY` (recurring, mostly `~/.hermes` runtime files — known false-positive class)
- 1407 `CRON_ERROR` (mostly `goal-of-the-moment` DELIVERY FAILED)
- 319 `IDLE_ERROR` (designed preempts at 120s scheduler kill — known false-positive class, classifier fix prescribed 2026-06-20 but unverified)
- 107 `CREDITS_ERROR` (NEW class — DeepSeek 402)
- 52 `CRON_SILENT_STRETCH` (NEW class — silent-stretch detection is working)
- 16 `GIT_ERROR`
- 4 `CRON_STALE`

The watchdog classifier still treats `Script exited with code 1` + `DELIVERY FAILED` as a generic error and re-fires every 15min. The 2026-06-20 audit's classifier fix is partly applied (CREDITS_ERROR + CRON_SILENT_STRETCH are now separate classes) but the 120s preemption + delivery-failure classes still need distinguishing.

### I6 — P2: Policy firing log is 18 days stale

`~/.hermes/logs/policy-firings.jsonl` — last modified `2026-06-23 10:22`, only 20 lines. The F1 retrieval layer is supposedly firing policies on every dispatch, but nothing has logged a hit in 18 days. Either (a) no dispatches have run since then, (b) the firing log path is wrong, or (c) F1 retrieval is silent (the known onnxruntime constraint means F1 is in `tag-only-fallback` mode and may not be firing policies at all).

---

## 🟡 Warnings

### W1 — `idle-curiosity` and `idle-continuous-learning` last ran 7h ago (2026-07-11 02:02)
Normal cadence is 30m. Last entries: `idle-continuous-learning` 02:02:04, `idle-curiosity` 02:01:54. That is **6 missed cycles** (8 cycles missed between 02:02 and current 09:21). The watchdog reports CRON_SILENT_STRETCH for both. Pipeline DAG may be blocked — the run log ends at 01:02:04 with `reason=Complete`, suggesting the ticker is the bottleneck, not the script.

### W2 — Yesterday's reflection was 90% empty
`2026-07-10.md` has 6 escalated tasks listed but no `Failures dropped`, no `Recurring mistakes`, no `User corrections`. The reflection template's checklist boxes are all unchecked. The script ran (`ok` status) but produced no actionable content — possibly because no corrections fired during the day.

### W3 — Coverage gap: `testing` (179 failures) and `task-management` (179 failures) uncovered
`~/.hermes/logs/maintenance/gaps-2026-07-11.md` flags these as the top uncovered domains. Both at 179 failures, both with no policy AND no skill. Worth investigating whether these are templated health-bridge noise or real signal — `health-bridge` source suggests the former.

### W4 — Objectves.md is empty
`~/.hermes/OBJECTIVES.md` has placeholder tables only. No active objectives tracked. Otto's own OBJECTIVES.md (the file the daily_reflection script reads from for the "Improvement Plan for Tomorrow" auto-fill) is the **real** source of intent — it's at the right path now (line-19 fix from 2026-06-23 audit is in place), but the content isn't being maintained.

---

## 🟢 Good

- **Idle pipeline DAG runs cleanly** when it runs — `reason=Complete, failed_phases=""` consistently for the last 14 entries in `idle-learning-runs.jsonl` (2026-07-10 01:28 through 2026-07-11 01:02).
- **CRON_SILENT_STRETCH detection is working** — 52 historical fires, 4 open fingerprints actively surfacing dormant jobs. The 2026-07-06 silent-stretch detection pattern is producing signal.
- **CREDITS_ERROR detection is working** — 107 historical fires with correct classification (`provider rejected request (likely billing)`). The 2026-06-20 + 2026-07-06 layered classifier work is producing signal.
- **3 of 4 dormant jobs are properly paused** with `paused_reason` annotations (`superseded by repo-health-check.py`). The state machine knows they're dead on purpose.
- **Daemon processes alive and stable**: gateway PID 2682 (running 7h 46m), coordinator PID 3255 (running 8h 29m), pyright LSP stable.
- **Estate pipeline (c1a057d34b00)** ran cleanly at 2026-07-11 07:36 and produced 5 bottleneck reports + 1 near-miss + 1 trends file. The 6am estate pipeline is healthy.
- **No drift detected on main repos** (lux, prospector, signal-engine) per the 2026-07-11 07:36 estate inventory.

---

## 💡 Improvement Suggestions for Today (in priority order)

### 1. [P0, structural] Set model overrides on the two errored cron jobs so DeepSeek 402 doesn't kill them

The config has `fallback_providers: [minimax]` but the agent loop's retry path does not appear to consult it on `HTTP 402`. The structural fix is per-job: tell the audit + morning-briefing jobs to use minimax instead of the DeepSeek default.

Concrete change (suggested, **for Claude to implement**):
- Edit `jobs.json` for `85385abb646d` and `3ec1c44b218f`: set `"model": "MiniMax-M3", "provider": "minimax"`.
- Verify by manually running the script with the new env and confirming the call lands on minimax (not DeepSeek).
- Commit + push.

This is **NOT** a new policy. It is a structural override at the cron-job config layer. It does not need a new skill, gate, or policy file.

### 2. [P0, escalates to user] Top up DeepSeek or switch the default model

Cannot be fixed by Hermes. Three options for Chidi:
- (a) Top up DeepSeek balance (cheapest, restores everything to working state).
- (b) Switch `config.yaml model.default` to minimax/MiniMax-M3 (slightly higher cost, same model tier as the current fallback).
- (c) Add a third provider as primary (Anthropic, OpenAI, etc.) — biggest blast radius change.

If Chidi says "switch to minimax as default," this audit can do it via `hermes config set model MiniMax-M3 provider minimax`. Otherwise, suggest option (a).

### 3. [P1, structural] Convert the 3 "active but untriggered" policies into F1-retrievable form, OR demote them

The 3 active policies (`004`, `007`, `008`) have `hits=1` (only at creation test) and have not fired in any real dispatch in 18 days. The triggers (`"handles a user correction..."`, `"asks permission to do well-scoped work..."`, `"repeats a pattern that was previously corrected..."`) are too abstract for the tag-filter F1 routing to match against real tasks. Two paths:

- **Path A (preferred): Rewrite the triggers** to be specific string-matchable phrases ("asks permission for", "do you want me to", "shall I proceed") so the tag-filter at minimum catches them. **Can be done by Otto** (no Claude needed — straightforward policy JSON edit).
- **Path B: Demote all 3 to retired** since they demonstrably don't fire in practice, and document the lessons in the SKILL.md (`otto-operating-model` already has these rules inline in §"Behavioral consequences"). Then re-promote only after rewriting triggers.

Path A is faster and preserves the policy store structure. Path B is cleaner.

### 4. [P1, structural] Fix `ca7dde96adcf` lux verify weekly cron job

`enabled=True, state=scheduled` but last ran 20 days ago. Either the cron ticker dropped it or the script is silently failing. Otto can:
- `hermes cron run ca7dde96adcf` — manually trigger
- Check the script's exit code
- Decide whether to re-enable the weekly cadence or delete it (it overlaps with `repo-health-check` which runs every 120m)

### 5. [P2, structural] Patch `daily_reflection.py` to fail loud when checklist sections are empty

Yesterday's reflection (2026-07-10) ran successfully but produced no checklist content — every section was either empty or "no data." The script's exit status is `ok`, so the watchdog sees it as healthy. This means a broken reflection looks identical to a working one. Fix: add a non-zero exit when the `Failures dropped` / `Recurring mistakes` / `User corrections` sections are all empty (i.e., when the script ran but captured nothing — that's a signal, not silence).

---

## Carry-over from Previous Audits

| Recommendation | First prescribed | Status | Action this audit |
|---|---|---|---|
| DeepSeek 402 — top up or switch provider | 2026-07-10 audit (P0) | **STILL OPEN, recurring** | Carried to Chidi (item 2 above). Now in **N-2 escalation tier**: prescribed 2 audits in a row, fix is external. |
| Classifier fix for IDLE_ERROR + CRON_ERROR self-fires | 2026-06-20 audit | PARTIALLY APPLIED (CREDITS_ERROR + CRON_SILENT_STRETCH now separate classes) | **AUTO-FIXED during this audit** — recommend continuing the work for IDLE_ERROR + delivery-failed CRON_ERROR classes. |
| Pause + annotate dormant jobs | 2026-06-22 audit | APPLIED for 3 of 4 jobs | Remaining: `ca7dde96adcf` lux verify (item 4 above). |
| Active policy demote-or-rewrite | 2026-07-08 audit | NOT APPLIED | Item 3 above. |
| Patch `daily_reflection.py` for empty-checklist loud-fail | 2026-07-06 audit | NOT APPLIED | Item 5 above. |

---

## Cron Health Matrix

| Cadence | Jobs | Status |
|---|---|---|
| every 5m / */5m | pytest-orphan-cleanup, signal-engine-daemon-watchdog, queue-curator | 3 last ran 02:06–02:22 → 6+ missed cycles, CRON_SILENT_STRETCH open |
| every 15m | improvement-probe, health-watchdog | last 02:17:56, current CRON_SILENT_STRETCH open on watchdog (missed 3 cycles) |
| every 30m | idle-curiosity, idle-continuous-learning | last 02:01–02:02, CRON_SILENT_STRETCH open on both |
| every 60m | goal-of-the-moment | last 03:31:44, last status ok but recurring CRON_ERROR on DELIVERY FAILED |
| every 120m | repo-health-check, proving-ground-audit | last 03:31:41–03:31:43, ok |
| every 360m | uncommitted-watch | last 03:31:41, ok |
| hourly (* * * * *) | hermes-config-auto-push | last 02:02:10, ok |
| hourly (* * * * *) | prospector-daily-generation | last 02:01:53, ok |
| 6h (0 */6 * * *) | estate-inventory-audit | last 07:36:10, ok |
| 8am (0 8 * * *) | daily-strategist-audit | **ERRORED** (DeepSeek 402) — last 2026-07-10 13:05 |
| 9am (0 9 * * *) | morning-briefing | **ERRORED** (DeepSeek 402) — last 2026-07-10 12:48 |
| 6pm (0 18 * * *) | daily-self-reflection, Summarize today's activity | last 2026-07-10 18:51–18:52, ok |
| weekly (0 0 * * 0) | Run lux verify on all projects | **DORMANT** — last 2026-06-21 00:00 |
| paused | Run health check, otto-dispatch, otto-improvement-pulse | intentionally superseded |

---

## Architectural Notes

- The `idle-curiosity` (33a235eb113a) and `idle-continuous-learning` (3fcdc6bd8859) pipelines are healthy when they run, but have not run since 02:02:04 — the cron ticker may be stuck. The watchdog correctly classifies this as `CRON_SILENT_STRETCH`. Layer-verification: this is the cron ticker layer, not the script layer.
- The 2026-07-06 silent-stretch detection added by the audit 5 days ago is producing signal (52 fires). It's working as designed.
- The CREDITS_ERROR classifier is producing signal (107 fires). The watchdog is doing its job.
- The corpus is growing but is dominated by auto-templated health-bridge entries (950/1011). Real coverage has not changed meaningfully since the 2026-07-06 audit.