# Hermes Agent UI Improvements — Spec
**Date:** 2026-07-31
**Source:** Otto + founder conversation
**Target:** Claude (Opus — this is design/review work, not execution)

---

## Context

Hermes currently surfaces through Telegram (primary), TUI, CLI, and a Streamlit control center. The founder operates almost entirely from a phone via Telegram. Current pain points:

- Information overload (estate audit messages are massive)
- Alert repetition (same escalated failure 3× in a row)
- Fragmented navigation (4+ commands to learn)
- No "what changed" — full audit every time
- Static button bars that don't adapt to context

The goal: a phone-first, glanceable, non-noisy interface where the estate speaks only when it has something new to say.

---

## 1. Alert Deduplication

**File:** `~/.hermes/hermes-agent/gateway/operator_shell/estate.py` (or wherever coordinator escalations are rendered to Telegram)

**Current behavior:** Every coordinator tick that finds the same escalated task re-emits it:
```
🔴 ESCALATED: probe relay latency self-test
🔴 ESCALATED: probe relay latency self-test
🔴 ESCALATED: probe relay latency self-test
```

**Target behavior:** Collapse repeated escalations into one line with an occurrence counter and last-seen time:
```
🔴 probe relay latency self-test (3rd occurrence · last 14:02 UTC)
```

**Implementation notes:**
- The coordinator already stores task state in `coordinator.db` — use the `escalated_at` and `last_fail_at` timestamps
- Render layer: deduplicate by task ID when formatting for Telegram. If N occurrences of the same task ID appear in the current tick's output, emit one line with the counter
- Re-expand on tap: button to see the full timeline
- Rate for non-escalated repeats too: `⚙️ Working on: X` appearing multiple times should also collapse

**Edge cases:**
- Two different tasks with similar names — dedupe by task ID, not message text
- Task resolves then re-escalates — the counter resets on resolution
- After 5+ occurrences, drop the emoji prefix and use a muted style

---

## 2. Progress as a Living Message

**Files:** `coordinator.py` (the progress-notify mechanism), `gateway/` (Telegram message editing)

**Current behavior:** Each status change sends a new Telegram message. The chat scrolls.

**Target behavior:** A single pinned/edited Telegram message that updates in-place:
```
⚙️ Active (2): Prospector [4m] · Signal Engine [12m]
🔴 Blocked (1): Haworks Platform — acceptance test
🟢 Done today: 3
```

**Implementation notes:**
- The gateway already has `edit_message_text` capability (Telegram Bot API)
- `coordinator.py`'s `progress_notify()` needs a `message_id` parameter — first call sends a new message and stores the ID; subsequent calls edit it
- Store the live-message ID per chat in `state.db` or a simple JSON file
- After a threshold (e.g., 20 edits or 1 hour), send a new message and archive the old one — prevents edit-rate limiting
- On session restart, look up the last known message ID and resume editing it

**What gets collapsed into this message:**
- Active task list with durations
- Blocked/escalated count
- Today's completed count
- Brief spend indicator

**What stays separate:**
- Explicit user queries and their responses
- `/panel` type cards (on-demand only)
- Alerts for NEW failures (first occurrence only — see #1)

---

## 3. Severity Summary (Default `/status`)

**File:** New gateway operator command or extension of `ceo_mode.py`

**Current behavior:** The full estate audit fires as one giant message.

**Target behavior:** A `/status` command returns a scannable summary:
```
🟢 Daemons 2/5 · 🟢 Cron 18/23 · 🔴 Missions 0/2
🔴 3 escalated · 🟡 1 blocked · 💰 $0.01 spent today

Tap to drill in:
  /daemons  /missions  /cron  /spend
```

**Implementation notes:**
- This is a lightweight probe — read-only aggregation of existing state
- Daemon count: count `running` vs total from launchctl state (already in `estate.py`)
- Cron count: count `ok` vs total from cron jobs (already in `prospector_daemon.py`)
- Mission count: from coordinator's task list, count active vs blocked
- Spend: from the coordinator or guard probe
- Each drill-in command opens a focused, short card (reuse existing panel rendering, just trim the output)
- The full `Otto audit` stays available but is not the default view

**Drill-in cards should be SHORT:**
- `/daemons` → one line per daemon, just emoji + name + status (not the full plist dump)
- `/missions` → one line per mission, status glyph + name + next step
- `/cron` → counts by status, failures only
- `/spend` → visual gauge + last 3 charges

---

## 4. "What Changed" Diff Mode

**File:** New script `~/.hermes/scripts/estate-diff.py` + Telegram command

**Current behavior:** Every audit restates the entire estate. The user must scan for changes.

**Target behavior:** `Otto diff` shows only what changed since the last check:
```
Since 09:36 UTC:
  + 🟢 prospector batch_size 5→15 (founder directive)
  - 🔴 watchdog still down (3h — no change)
  + ⚠️ NEW: prospector guard probe failed (exit 1)
  ~ 🟡 missions: Haworks escalated → resolved
```

**Implementation notes:**
- Store a snapshot of the last audit at `~/.hermes/state/last-audit-snapshot.json`
- On `Otto diff`, run a fresh inventory probe, compare to the snapshot, emit only diffs
- After emitting, update the snapshot
- Categories to diff:
  - Daemon status changes (running → down, pid changes)
  - New/removed cron failures
  - Mission status transitions
  - Config changes (batch_size, interval, etc.)
  - New escalated tasks
- Pure read-only probe — no state mutation
- Exit 0 if no changes ("No changes since 09:36")

---

## 5. Context-Aware Button Bar

**Files:** `gateway/operator_shell/estate.py`, `prospector_daemon.py`, `ceo_mode.py`

**Current behavior:** Static buttons on every panel:
```
♻️ Restart · ⏹ Stop · ▶️ Start · ⚙️ Params · 🗓 Cron · 📜 Logs
```

**Target behavior:** Buttons adapt to current state:

| State | Primary buttons |
|-------|----------------|
| All healthy, idle | 🚀 Fleet · 🗓 Cron · 🔍 Audit |
| Mission active | ⏸ Pause · 🎯 Steer · ❌ Abort |
| Task escalated | ✅ Approve · 🔄 Reassign · 🗑 Dismiss |
| Spend paused | ▶️ Resume · 💵 Set cap · 📊 Why |
| Daemon down | 🔄 Restart · 📜 Logs · 🔍 Diagnose |
| Cron job failing | ▶️ Run now · ⏸ Pause · 📜 Logs |
| zero_yield alert | 🔍 Diagnose · ⚙️ Params · 🧪 Golden set |

**Implementation notes:**
- Each panel's `render_*()` function already returns `(text, buttons)`
- Add a `context` dict passed to render functions with current state
- `context` includes: active mission count, escalated task count, spend status, daemon health, cron health, latest alert codes
- The render function switches button sets based on context
- Keep a "More" button that expands to show the full static button set for power users

---

## 6. Unified `/status` Entry Point

**Files:** `ceo_mode.py`, `gateway/operator_shell/estate.py`

**Current behavior:** 
- `/panel` — mission card
- `/inbox` — approvals
- `/fleet` — project list
- `/cron` — job list

Four separate commands the user must remember.

**Target behavior:** `/status` shows everything at once, with drill-in buttons:
```
🤖 Otto · mode ceo

🟢 2/5 daemons · 🟢 18/23 cron · 🔴 0/2 missions
💰 $0.01 / $20.00 ▓░░░░░░░░░ 0%

⚙️ Active: rewriting prospector ranking (Claude Code · 4m)
🔴 Blocked: Haworks Platform (acceptance test)

  🚀 Fleet  🗓 Cron  🔍 Audit  💰 Spend  ⚙️ Active
```

**Implementation notes:**
- This is a composition of existing probes, not new infrastructure
- Gateway command `/status` → calls `estate.py` with action `status_summary`
- The summary aggregates: daemon count, cron count, mission count, spend, active tasks, blocked tasks
- Each section is one line max — detail is one tap away
- The separate commands (`/panel`, `/fleet`, etc.) still work for deep dives
- CEO mode already intercepts short noise → mission card; `/status` should also be reachable via `Otto status`

---

## 7. Morning/Evening Digest (Primary Delivery)

**Files:** `~/.hermes/scripts/morning_brief.py`, `~/.hermes/cron/jobs.json`

**Current behavior:** 
- 23 cron jobs, many delivering output directly to the main DM
- `morning-briefing` exists but is just one of many messages
- Cron output topic exists but isn't the default delivery target for all jobs

**Target behavior:**
- **Morning digest (9am):** Overnight events, today's plan, any open alerts
- **Evening digest (6pm):** What shipped, what blocked, spend summary, tomorrow's plan
- **Cron output:** All routine job output goes to a dedicated Telegram topic (`🧵 cron`). Only exceptions (NEW failures, not repeats) reach the main DM
- **Format:** Brief, scannable. Failed jobs with one-line reason. Successful jobs silent.

**Implementation notes:**
- `morning_brief.py` already exists and runs at 9am — extend it
- Add `evening_brief.py` for the 6pm slot
- Change delivery target for cron jobs that currently deliver to `origin` — route them to the cron topic
- Add a `deliver_on_error_only` flag to cron jobs: silent on success, DM on failure
- The digest scripts pull from: coordinator task list, watchdog alerts, cron job statuses, spend ledger, git uncommitted status

**Morning digest template:**
```
🌅 Morning · 2026-07-31 09:00 UTC

Overnight:
  🟢 prospector: 15 candidates → 3 PASS (batch_size: 15)
  🔴 watchdog: still down (ping not responding)
  🟡 2 cron jobs had errors (summarize, prospector guard)

Today:
  ⚙️ 1 active mission: prospector ranking rewrite
  🔴 3 escalated tasks need attention
  💰 Spend cap: $20.00 (used $0.00 today)

  /missions  /inbox  /audit
```

---

## 8. Visual Spend Gauge

**Files:** `gateway/operator_shell/estate.py`, wherever spend is displayed

**Current behavior:** `💰 $0.01 · 32/80` — cryptic, requires mental math.

**Target behavior:** 
```
💰 $0.01 / $20.00 ▓░░░░░░░░░ 0%  [daily cap]
```
At 75%: turns yellow. At 90%: turns red. Includes the cap type (daily/monthly).

**Implementation notes:**
- Generate a 10-segment Unicode block-character bar: `▓` for filled, `░` for empty
- Color by threshold: <75% neutral, 75-90% 🟡, >90% 🔴
- Show both absolute ($0.01) and cap ($20.00) with the cap type label
- Also works inline: `💰 ▓░░░ 25%` for space-constrained contexts
- Pull spend data from: guard probe (`today_spend_usd`), coordinator ledger, or cron job output
- Pure display change — no new data source needed

---

## Implementation Priority

| # | Idea | Effort | Impact | Depends on |
|---|------|--------|--------|------------|
| 1 | Alert deduplication | Small (render-only) | High (kills #1 annoyance) | None |
| 4 | "What changed" diff | Medium (new script) | High (dramatically shorter reads) | Snapshot storage |
| 3 | Severity summary | Small (composition) | High (one-tap clarity) | None |
| 5 | Context-aware buttons | Medium (per-panel) | Medium (fewer taps) | #3 |
| 6 | Unified /status | Small (composition) | Medium (fewer commands) | #3 |
| 7 | Morning/evening digest | Medium (extend existing) | Medium (less noise) | Cron delivery routing |
| 2 | Living progress message | Large (message editing, state) | High (no scroll) | Coordinator changes |
| 8 | Visual spend gauge | Small (render-only) | Low (nice-to-have) | None |

**Recommended order:** 1 → 4 → 3 → 5/6 → 7 → 2 → 8

---

## Design Principles

1. **Phone-first.** Every card must be readable in a Telegram message on a phone screen. Tables are OK; walls of text are not.
2. **Silent on success, loud on change.** A healthy daemon doesn't ping. A daemon that was down and recovers DOES ping. A daemon that stays down pings once, then rate-limits.
3. **One tap to action.** Every status line should have a button that does the obvious next thing.
4. **State is a probe, not a paragraph.** Every claim in the UI is backed by a live probe. No cached narrative.
5. **No self-certification.** The UI never says "all good" unless the proof probe says so.
