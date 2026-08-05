# Otto Recursive Self-Improvement — Complete Specification
**Date:** 2026-08-02
**Status:** Building

## 0. North Star

Otto should detect problems, fix them, learn from the fixes, and get better over time — measurably. Every time the founder has to intervene manually, Otto should create a policy so it handles that situation automatically next time. The system should compound: each week's improvements build on the last.

## 1. Architecture

```
                    ┌──────────────────────┐
                    │   Ops Monitor        │  runs every idle cycle (~30min)
                    │   (ops-monitor.py)   │  checks moat, credits, cron
                    │   → auto-pause       │
                    │   → propose policies │
                    └──────────┬───────────┘
                               │
                    ┌──────────▼───────────┐
                    │   Self-Audit         │  runs daily + weekly
                    │   (self-audit.py)    │  measures effectiveness
                    │   → daily snapshot   │  tracks week-over-week Δ
                    │   → weekly deep dive │  compounds learnings
                    └──────────┬───────────┘
                               │
                    ┌──────────▼───────────┐
                    │   Policy Injection   │  runs on every agent call
                    │   (memory_retrieval) │  injects relevant policies
                    │   → filtered by task │  into Otto's context
                    └──────────┬───────────┘
                               │
                    ┌──────────▼───────────┐
                    │   Policy Enforcer    │  pre-action gate
                    │   (policy-enforcer)  │  blocks bad behaviors
                    │   → classify action  │  before they execute
                    └──────────────────────┘
```

## 2. Feature Specifications

### 2.1 Return Summary ("What happened while I was away?")

**Trigger:** First user message after >1 hour of inactivity.
**Behavior:** Otto appends one line under its response:
```
---
_While away (95m): 🔭 moat down · 4 cron errors · 💰 $6.03 spent · ⏸ Prospector auto-paused_
```

**Implementation:**
- Store last interaction timestamp per chat
- On new message, check elapsed time
- If >1h, run `ops-monitor.py --check all --summary` 
- Append the one-liner to Otto's response
- File: `~/.hermes/plugins/otto-inbound/__init__.py` (pre_gateway_dispatch)
- File: `~/.hermes/scripts/return-summary.py` (probe)

### 2.2 Daily Digest (9am)

**Trigger:** Cron job at 9am daily.
**Behavior:**
```
☀️ *Good morning* — Tue Aug 3

*Yesterday:* 🔭 moat down (3h) · 116 prospector runs (22 ok, 94 err) · $6.03 spent
*Now:* 🟡 Engine running · ⏸ Prospector paused (moat) · 4 cron failing · 2 decisions waiting

*Top actions:*
1. Top up Cursor credits (moat dead since yesterday 15:00)
2. Approve money fence c1d2a4dd
3. Check 4 failing cron jobs
```

**Implementation:**
- New script: `~/.hermes/scripts/daily-digest.py`
- Composes: ops-monitor, prospector ticks, cron health, inbox count
- Cron entry in `~/.hermes/cron/jobs.json`

### 2.3 Auto-Pause on Moat Failure ✅ (done)

Already built in `ops-monitor.py`. Verified working — auto-created PAUSE file on 7 consecutive failures.

### 2.4 "Pause Prospector" Button on Moat Concern

**Trigger:** When moat concern appears on mission card.
**Behavior:** Two buttons instead of one:
```
[🔭 Check Prospector] [⏸ Pause Prospector]
```

**Implementation:**
- `_concerns()` in `mission.py` returns a third element for secondary action
- `mission_buttons()` checks for secondary action and adds a second button
- Or simpler: add a dedicated "pause_prospector" action that creates PAUSE and refreshes

### 2.5 Yesterday Comparison

**Trigger:** Always visible on 24h summary line and spend gauge.
**Behavior:**
```
🟡 24h: 117 runs · 22 ok · 95 err · $6.03 spent (yesterday: $4.21, 45 runs)
💰 Spend $6.03/20 (↑ $1.82 from yesterday)
```

**Implementation:**
- `_daily_summary()` in `prospector_daemon.py` reads yesterday's ticks
- `_burn_today()` in `mission.py` adds yesterday comparison

### 2.6 Spend Trend on Mission Card

**Behavior:** Shows ↑ or ↓ with delta.
**Implementation:** Modify `_burn_today()` in `mission.py`.

### 2.7 Undo Toast

**Trigger:** After any mutating action (pause, resume, restart, config change).
**Behavior:** Toast says "⏸ Prospector paused · [Undo]" — the Undo button reverses.
**Implementation:**
- `push_undo()` in `proof.py` stores the reverse action
- Toast includes undo callback
- File: `estate.py` `_finish()` wrapper

### 2.8 Log Search from Phone

**Trigger:** Natural language: `logs prospector moat`, `logs gateway error`, `logs coordinator`
**Behavior:** Returns last 15 lines of matching log, grepped for the search term.
**Implementation:**
- New natural_ops pattern: `logs <source> <filter>`
- New action: `estate:logs:<source>:<filter>`
- New function: `render_log_search()` in new file or in existing daemons module

### 2.9 Error Explanation

**Trigger:** When displaying moat_preflight errors.
**Behavior:** Parse the raw error string and show plain English:
```
⚠️ Cursor CLI: usage limit hit → top up at cursor.sh
⚠️ Claude CLI: credit balance too low → add credits at anthropic.com
```
**Implementation:** `_cron_outcome_lines()` error display section.

### 2.10 Ranked Action Suggestions

**Trigger:** `what now` natural language command (already routes to smart_panel).
**Behavior:** Shows ranked list:
```
*What you should do:*
1. 🔴 Top up Cursor credits — moat dead since 15:00 (95 min)
2. 🔴 Fix 4 failing cron jobs — `Summarize activity`, `config-auto-push`, ...
3. 🟡 Approve money fence c1d2a4dd
4. 🟢 All daemons healthy
```
**Implementation:** New panel `render_what_now()` or enhance smart_panel.

### 2.11 One-Tap "Fix Everything Safe"

**Trigger:** Button on status/smart panel.
**Behavior:** Runs all safe automated fixes:
- Clear stale PAUSE files if moat is healthy
- Kickstart hung daemons
- Re-enable disabled cron jobs that failed transiently
- Restart coordinator if heartbeat stale
Does NOT: move money, change config, approve decisions.
**Implementation:** New action `estate:fix_all_safe` with confirmation card.

## 3. Self-Audit System (Daily + Weekly, Compounding)

### 3.1 Daily Snapshot

**Runs:** Every idle cycle, but writes a daily summary file.
**File:** `~/.hermes/logs/self-audit/daily/YYYY-MM-DD.json`
**Contents:**
```json
{
  "date": "2026-08-02",
  "effectiveness": {
    "policy_firings": 0,
    "injections_with_policies": 5,
    "injection_total": 12,
    "auto_pauses": 1,
    "policies_proposed": 3
  },
  "failures": {
    "total_errors": 47,
    "moat_preflight": 40,
    "api_credits": 5,
    "cron": 2
  },
  "estate": {
    "prospector_runs": 117,
    "prospector_ok": 22,
    "prospector_err": 95,
    "spend_usd": 6.03,
    "engine_running": true,
    "decisions_waiting": 2,
    "cron_failing": 4
  },
  "score": 0.42
}
```

### 3.2 Weekly Deep Dive

**Runs:** Sunday 6pm (or via idle pipeline with --force).
**File:** `~/.hermes/logs/self-audit/weekly/YYYY-WXX.md`
**Contents:** Markdown report with:
- Week-over-week comparison of all metrics
- Policies created vs retired
- Top 3 failures and whether they were caught
- Improvement velocity: is the system getting better?
- Learning: what patterns emerged this week?

### 3.3 Compounding Score

**Metric:** "Otto Effectiveness Score" (0.0-1.0) computed daily.
**Formula:**
```
score = (
  0.30 * (auto_fixes / total_failures)          // did Otto fix things before I noticed?
  + 0.25 * (injections_with_policies / total_injections)  // are policies reaching Otto?
  + 0.20 * (policies_fired / total_actions)     // is the enforcer working?
  + 0.15 * min(policies_proposed_this_week / 3, 1.0)  // is Otto learning?
  + 0.10 * (1.0 if engine_healthy else 0.5)    // is the estate healthy?
)
```

**Display:** Shown on self-audit panel and in daily digest. Tracked over time in a JSONL file for charting.

### 3.4 Improvement Velocity

**Tracked metric:** Week-over-week Δ in effectiveness score.
**File:** `~/.hermes/logs/self-audit/velocity.jsonl`
**Goal:** Score should trend upward. Flat or declining = Otto isn't learning.

## 4. Fix Policy Enforcer

### Root cause analysis
The enforcer (`policy-enforcer.py`) hasn't fired since June 18. It classifies actions as AUTO-EXECUTABLE, NEEDS_HUMAN_INPUT, or NEEDS_CLARIFICATION. But:
1. It may not be called at all (check if `dispatch_gate.py` is importing it)
2. It may be classifying everything as AUTO-EXECUTABLE (no human-needed detections)
3. The firing log shows old entries but nothing recent

### Fix
1. Verify `dispatch_gate.py` actually calls `policy-enforcer.py`
2. Add a "policy_firing" log for EVERY classification (not just blocked ones)
3. Add a self-test: when enforcer loads, classify a known test case and verify it fires
4. Hook into the agent's pre-action path

## 5. Monitoring Dashboard

### Panel: "🧠 Otto Health" (`estate:otto_health`)

Shows Otto's self-improvement metrics:
```
🧠 *Otto Health* — self-improvement dashboard

*This week:* score 0.42 (↑0.15 from last week)
  Auto-fixes: 1/47 failures caught
  Policy injection: 5/12 relevant (42%)
  Enforcer: 0 firings ⚠️
  Learning: 5 policies proposed

*Policies:* 13 total (5 ops, 3 auto, 5 legacy)
  Created this week: 5 · Retired: 0 · Active: 13

*Last 7 days score:* ▁▁▁▂▃▄▄ (trending up)

*Top gaps:*
  1. Enforcer not firing — policies exist but never block actions
  2. Memory retrieval needs embedding layer (numpy missing)
  3. Cron orphans not auto-fixed
```

## 6. Implementation Order

### Wave 1 (now): Core plumbing
1. Return summary (`return-summary.py` + otto-inbound hook)
2. Yesterday comparison (`_daily_summary`, `_burn_today`)
3. Log search from phone (natural_ops + render)
4. Error explanation (parse moat errors)
5. "Pause Prospector" button on moat concern

### Wave 2: Intelligence
6. Daily digest (cron job + script)
7. Ranked action suggestions (smart_panel enhancement)
8. Undo toast (proof.py + estate.py)
9. One-tap "fix everything safe"

### Wave 3: Self-improvement hardening
10. Daily self-audit with compounding score
11. Otto Health monitoring panel
12. Fix policy enforcer
13. Weekly deep dive with velocity tracking

## 7. Files Changed

| File | Change |
|------|--------|
| `scripts/ops-monitor.py` | ✅ Created — moat/credits/cron checks |
| `scripts/self-audit.py` | ✅ Created — weekly analysis |
| `scripts/memory_retrieval.py` | ✅ Fixed — policy filtering + lower threshold |
| `scripts/idle-learning-run.sh` | ✅ Updated — Phase 2.5 + 2d |
| `policies/pol-ops-*.json` | ✅ Created — 3 operational policies |
| `memories/MEMORY.md` | ✅ Tagged — 8 entries with [tags:] |
| `meta/OFF_SWITCH` | ✅ Created — RSI armed |
| `scripts/return-summary.py` | 🔨 Build — away-message probe |
| `scripts/daily-digest.py` | 🔨 Build — morning briefing |
| `gateway/operator_shell/mission.py` | 🔨 Update — yesterday comparison, pause button |
| `gateway/operator_shell/prospector_daemon.py` | 🔨 Update — yesterday comparison |
| `gateway/operator_shell/estate.py` | 🔨 Update — undo toast, fix_all_safe |
| `gateway/operator_shell/natural_ops.py` | 🔨 Update — logs command |
| `gateway/operator_shell/otto_health.py` | 🔨 Build — monitoring dashboard |
| `plugins/otto-inbound/__init__.py` | 🔨 Update — return summary hook |
