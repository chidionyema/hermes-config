# Hermes / Otto Cockpit Audit — Complete UX & Workflow Review
**Date:** 2026-07-31 (post-P0/P1 batch)
**Auditor:** Otto (empirical probe + code read) — receipts attached
**Question:** Is the current UI / way-of-working good enough? What's the path to "seamless and heavenly"?

---

## TL;DR

**The cockpit is functional but rough.** It works because of a recent heavy round of
P0/P1 fixes (dedup, severity legend, breadcrumb, one-tap verbs, loading indicator,
preflight cache, callback guards). The remaining gaps are:

1. **Mission card is the slowest panel (5–7s cold) and is also the most-tapped.** Every
   `/panel`, every `Otto now`, every `hi/ok`, every `[⚡️ Now]` button lands here. It
   gets 5–10× more taps than any other panel.
2. **Hard-no panels still take 60–70s.** `st_status` 64s, `st_health` 74s, `st_reconcile`
   hits the 240s timeout. Pre-flight cache hides this on second tap, but the *first*
   tap from any phone is brutal.
3. **Truncation hides the truth.** The mission card truncates failure messages with
   `…` (`Signal Engine daemon…`) so the operator sees an alert with no clue. They have
   to tap Inbox → Inspect to read the full message. Two taps is too many for "what's
   broken right now".
4. **No timestamps on operational state.** Daemon status lines: `🟢 keepawake · pid 89345`.
   Last-run heartbeat on prospector: `sleeping 43m`. The *delta* is shown, not the *when*.
   When you tap `📜 Coord logs`, the log file's mtime is shown, but the state itself has
   no absolute timestamp.
5. **Single-window pinning creates noise.** When the mission card is pinned to a chat
   and the user scrolls past it, every panel operation re-edits the same message in
   place. The audit card / inbox card / fleet card all try to edit the same pinned
   message — race conditions and toast spam.
6. **The 1,626-line `estate.py` is a god file.** Every new action goes in here. Every
   new panel adds an `if action == ...` branch. This is the single biggest structural
   risk to velocity.
7. **5 cron jobs disabled with `last_status=error` sitting there for weeks** (some since
   2026-06-18). Not surfaced anywhere.

**Net verdict:** ship the P0 batch below → operator UX drops to <500ms median →
"seamless" is real. Then P1 (god-file split, rich panels, dedupe by state) → "heavenly"
is on the table. P2 (cron health UI, async probes, living progress message) is the
ceiling and the multi-day work.

---

## 1. Empirical Audit (live probe results)

### 1.1 Panel latency matrix — fresh cold cache

| Panel | ms | chars | btns | Notes |
|------:|---:|------:|-----:|-------|
| `refresh` | **6,307** | 562 | 7 | Mission card — 10× slower than next-worst |
| `run` | 3 | 562 | 7 | Cached |
| `activity` | 2 | 562 | 7 | Cached |
| `find` | 2 | 562 | 7 | Cached |
| `brain` | 2 | 562 | 7 | Cached |
| `tune` | 2 | 562 | 7 | Cached |
| `inbox` | 3 | 562 | 7 | Cached |
| `rsi` | 3 | 562 | 7 | Cached |
| `brief` | 754 | 230 | 3 | Calls `render_executive_brief()` — not cached |
| `missions` | 19 | 173 | 2 | Cached |
| `status` | 163 | 480 | 3 | Cached |
| `diff` | 390 | 84 | 2 | Runs `estate-diff.py` subprocess |
| `fleet` | 1,352 | 334 | 5 | Probes launchd for 5 subsystems |
| `daemons` | 322 | 777 | 7 | Probes launchd for all daemons |
| `host` | 146 | 341 | 3 | pmset + load + net probes |
| `prospector_daemon` | 140 | 1,000 | 6 | Reads daemon logs |
| `pd_params` | 21 | 243 | 4 | Cached |
| `pd_cron` | 17 | 394 | 3 | Cached |
| `se_params` | 13 | 450 | 4 | Cached |
| `se_logs` | 80 | 2,840 | 3 | Reads 4 log files |
| `system_fuel` | 55 | 337 | 1 | Cached |
| `list_active` | 22 | 19 | 1 | Cached |
| **`st_status`** | **64,015** | 159 | 3 | **1+ minute cold** |
| **`st_health`** | **73,963** | 232 | 3 | **75 seconds cold** |
| **`st_reconcile`** | >240,000 | — | — | **Timeout** (probe hits 240s cap) |
| **`builds`** | **14,388** | 666 | 2 | GitHub API call |

**Median panel: 22ms. Worst: 240s+. Mean: skewed by st_*.**

### 1.2 Cache effectiveness (after preflight P1-1)

| Action | Cold | Warm | Speedup |
|--------|-----:|-----:|--------:|
| `st_status` | 64s | 6ms | 10,000× |
| `st_health` | 74s | 8ms | 9,000× |
| `builds` | 14s | 7ms | 2,000× |
| `refresh` | 6s | 952ms | 6× |

**Cache hits work. Cache misses still brutal.** First-tap UX is the bottleneck.

### 1.3 Real panel output — what the user sees

**`refresh` (mission card, 562 chars):**
```
🎛 *Cockpit* · *🟡 BLOCKED* — 4 need you
🖥 Host: AWAKE · online
💰 `$0.01 · 35/80`  ·  📈 `82%` · 23 done / 5 ask
🧠 RSI `OFF` · OFF_SWITCH absent · arm via 🧠 RSI
🧱 BLOCKED `c1d2a4dd` failure: Signal Engine daemon…    ← TRUNCATED
🚀 `Prospector ship` BLOCKED · M4: Land the acceptance test as…    ← TRUNCATED
🚀 *1 blocked mission(s)* — tap *Open missions*…
🧵 cron `main DM (ok)`
*Needs you (2):* → 📥 Decide (4) → 🚀 1 blocked
```

**`fleet` (1,352ms, 5 buttons):**
```
🚀 *Fleet*
🟢 signal `healthy (launchd-supervised)` · eq `$9,797` · hb `10s` · `paper`
🟢 sched `pid 94846` · hb `sleeping` 43m · 19:01     ← ONE TIMESTAMP, DELTA ELSEWHERE
⚪ *Prospector* · dirty(18) · inflight 0     ← "dirty" is unexplained
⚪ *Signal* · dirty(24) · inflight 0
⚪ *TIE* · dirty(9) · inflight 0
⚪ *Haworks* · dirty(95) · inflight 0          ← 95 is alarming without context
```

**`daemons` (322ms, 7 rows, 18 buttons):**
```
🟢 `gateway` · pid 5452 · fenced
🟢 `coord` · pid 56290
🟢 `watch` · armed · last exit 0 · runs 301 · interval    ← "armed" is internal jargon
🟢 `prog` · armed · last exit 0 · runs 26 · interval
🟢 `rsi` · armed · last exit 0 · runs 3 · calendar
🟢 `tie-review` · armed · last exit (never exited) · runs 0 · calendar    ← ⚠️ should explain
🟢 `otto-http` · pid 2922
⚫ `cockpit` · plist on disk, not loaded · retired    ← dead but in the list
⚫ `ngrok` · plist on disk, not loaded · retired
```

**`prospector_daemon` (140ms, 6 rows, 14 buttons):**
```
⚙️ *Prospector control*
_captured 2026-07-31 19:45 UTC · scheduler=KeepAlive daemon · watchdog=15m oneshot_  ← TIMESTAMP HERE
🟢 *scheduler* · pid 94846
🟢 *watchdog* · armed · last exit 0 · runs 49
🟢 *control-center* · pid 77927
*Params*
• interval `7200`s (2h) · concurrency `2`
• batch_size `15` · daily_cap `$20.0`               ← batch_size change not acknowledged
• PAUSE file `off` · watchdog every `900s`
💓 hb `sleeping` · `43m` · `2026-07-31 19:01 UTC`   ← ABSOLUTE TIME — GOOD
*Cron + last runs*
🟢 `df1c4914` *prospector-daily-generation* [ok] last 44m ago
   next `2026-07-31T21:00:00+01`
*Daemon ticks (latest)*
🔴 skip 43m ago — `paused: /Users/chidionyema/.../store/scheduler/PAUSE`
🔴 skip 44m ago — `paused: ...`                       ← same root cause 3x — should be 1
🔴 skip 57m ago — `paused: ...`
*Recent log* _(1h ago)_                              ← RELATIVE only, no absolute
   `2026-07-31 18:38 UTC        ⚠️  [dead_gate] …`
```

**`run` (cockpit.py:447, 19 buttons):**
```
🎛 *Run* — the verbs. Nothing here changes configuration.
*💸 Whole estate* — `live`
*💹 Signal engine* — `running`
*🔭 Prospector* — `live`
*⚙️ Daemons*
*👁 Look*
```

### 1.4 Findings — UX defects that hurt daily use

| ID | Defect | File:line | User impact |
|----|--------|-----------|-------------|
| **U1** | Mission card truncates `BLOCKED` failures with `…` | `mission.py` | Operator sees alert with no actionable context. Two taps to read full text. |
| **U2** | Mission card is the only panel that doesn't use `compose()` legend | `mission.py:488` | Inconsistent with every other panel. |
| **U3** | "Dirty(18)" / "dirty(95)" / "inflight 0" on fleet — no glossary | `fleet.py` | Operator can't tell if 95 dirty items is good or catastrophic. |
| **U4** | "armed" / "fenced" / "calendar" / "interval" launchctl jargon | `daemons.py`, `prospector_daemon.py` | Jargon-heavy. Plain English explanation missing. |
| **U5** | "last exit (never exited) · runs 0" → ⚠️ but no explanation of what to do | `daemons.py` | Operator sees warning, no next step. |
| **U6** | Three 🔴 skip entries on `prospector_daemon` are the same `paused:` root cause | `prospector_daemon.py:_last_ticks` | Activity dedup fix (P0-4) didn't reach this panel — same noise repeats. |
| **U7** | Prospector log "Recent log _(1h ago)_" — relative only, no absolute | `prospector_daemon.py:674` | User asked for absolute timestamps. Status line has them. Log section doesn't. |
| **U8** | Brief panel shows BLOCKED truncated failure (`Signal Engine daemon…`) | `voice_brief.py` | Same U1 issue, different panel. |
| **U9** | Inbox panel shows BLOCKED tasks without severity-on-row | `inbox.py` | All four rows look the same; can't tell which is most urgent. |
| **U10** | `system_fuel` panel toast reads "Fuel" but text says "DONE" — toast doesn't match content | `estate.py:1499` | Toast says "Fuel" — no signal of state change. |
| **U11** | `restart` confirm card says "♻️ *Restart coordinator?*" but text never says which thing | `estate.py:1422` | Ambiguous when there are multiple daemons. |
| **U12** | Each panel's last-edit timestamp is shown only on mission card | `mission.py:488` | Inbox/daemons/etc have no "what time was this refreshed". |
| **U13** | Daemon panel says "♻️ Restart coord" — only coordinator is restartable from here | `daemons.py` | Other daemons show logs only. Inconsistent verb coverage. |
| **U14** | On `pd_stop` confirm, the success path returns the daemon panel, not the params | `estate.py:863` | After confirming stop, user lands back at the same confirm-context parent. |
| **U15** | `setup_cron_topic` shows the same card twice if user retried — uses `view.needs_cron_topic_setup` | `estate.py:1275+1338` | "Cron topic ✓" + full card may appear together. |
| **U16** | "now" alone produces `⚠️ Unknown action `now`` + mission card concatenation | `estate.py:1622` | `now` is documented in mission card footer but a literal `now` token still routes to unknown. |

---

## 2. Workflow Audit

### 2.1 Tap-paths that take too many taps

| Goal | Current path | Taps | Ideal |
|------|--------------|-----:|-------|
| Bounce the signal engine | Run → ♻️ Restart (signal) | 2 | 1 |
| Approve a blocked decision | Inbox → 👁 Inspect → ✅ Approve | 3 | 2 |
| Clear prospector PAUSE | Prospector daemons → ▶️ Clear PAUSE | 2 | 1 |
| See why a daemon is down | Daemons → 📜 Logs → read 8h-old output | 3 | 2 with inline hint |
| Change leverage | Tune → Sizing → lev 2x → Confirm | 4 | 3 |
| Find why signal engine won't start | Brief shows "Signal Engine daemon…" → Missions → Inbox → Inspect | 4 | 1 (tap truncated text → full text inline) |

**Tap-budget target:** 2 taps for 80% of operations. Currently the worst case (approve blocked decision) is 3 taps and only because no panel offers ✅ inline.

### 2.2 Commands the user must know

```
/panel  /inbox  /fleet  /brief  /cron  /busy  /notify  /revert
/missions  /audit  /help  /sethome
```

12 commands. Plus natural-language phrases: `Otto now`, `Otto mission foo`, `pause prospector`, `store status`, etc.

**No command helps the user discover what to say next.** `/help` is generic. There's no `Otto ?` to list common verbs.

### 2.3 Cron job health — orphaned failures

5 jobs disabled with `last_status=error`:
```
⚪ Summarize today's activity    last=error  (since 2026-07-30)
⚪ Run health check on all      last=ok     (but disabled)
⚪ daily-strategist-audit       last=error  (since 2026-07-29)
⚪ otto-improvement-pulse       last=ok     (but disabled since 2026-06-21)
⚪ otto-dispatch                last=ok     (but disabled)
```

**Nothing in the operator_shell surfaces this.** The cron panel is healthy because it filters out disabled jobs. Operator has no way to discover "I have 5 jobs that used to run and now don't".

### 2.4 Error states and recovery

| Failure | What user sees | What they can do |
|---------|----------------|------------------|
| Gateway crash | Panel stays old; no signal | None from cockpit — must SSH |
| Coordinate down | All cards show stale data | Restart from Run → Restart coordinator |
| Prosp daemon hung | Daemon card shows 🟡 | Restart from Run |
| Mission blocked | Mission card shows it (truncated) | Inbox → Inspect (3 taps) |
| Budget tripped | Card shows `Budget: TRIPPED` with 🔓 Override button | 1 tap to override |
| Full Disk Access denied | "python@3.12 lacks Full Disk Access. Needs one-time founder grant." | None — text-only fix |
| `createForumTopic` fail | Long explainer card | "Keep cron in this chat" |
| Unknown action | `⚠️ Unknown action X` + mission card | Refresh |

**Recovery paths are uneven.** Budget override is 1 tap; FDS grant is a wall of text.

---

## 3. Code-level structural issues

### 3.1 `estate.py` god file (1,626 lines)

Every new operator action adds an `if action == ...` branch in `_dispatch`. There are now **47 distinct actions** all funnelled through one function. Per-action code is **12–60 lines**, but the dispatch logic (`_finish`, idempotency, proof receipts, toast, post-action side-effects) is duplicated 47×.

The `_finish` wrapper alone is 7 lines and gets repeated for every action. That's ~330 lines of pure ceremony.

**Refactor target:** split into `estate/dispatch/{daemons,signal,store,code,inbox,meta,surface}.py` with `def dispatch(action, arg, ctx) -> PanelView` per module. `_dispatch` becomes a router.

Effort: ½ day. Risk: medium — the current contract is `handle_estate_action(action: str, request_id: str = "") -> PanelView`. Surface it explicitly in the new layout.

### 3.2 `prospector_daemon.py` (940 lines) — second-largest

Mixes: param validation, daemon health probes, cron-job outcome reading, log tailing, confirm-card rendering, ARM flows. All in one file.

`signal_engine.py` (996 lines) is the same shape. These are paired siblings — both are "control surface for one project".

**Refactor target:** pull `_last_ticks()` (the root-cause dedup is missing here, see U6) and `_tail_lines()` (U7) into a shared `log_utils.py`. Move `_params_lines()` and `confirm_card()` into `prospector_daemon/params.py`.

### 3.3 Hardcoded timings and assumptions

| Where | What | Risk |
|-------|------|------|
| `telegram.py:4322` | "Telegram only gives ~15s before query id expires" | Hardcoded 15s — if Telegram changes, this breaks silently |
| `estate.py:657` | "To stop the daemon writing to prod, say `pause prospector`" | Suggestion text is fixed; could be wrong if verbs change |
| `telegram.py:6250` | `max_commands=MAX_COMMANDS_PER_SCOPE` | Magic number — what is it? |
| `preflight.py:148` | TTLs: `st_status=120s, builds=60s, refresh=10s` | Per-panel, but no documentation of why |
| `mission.py` | `_2026-07-31 19:15:38 UTC · auto-refresh · say `now` to force_` | Timestamp format hard-coded |

### 3.4 Magic constants

- `_TAIL_LINES = 4` in `prospector_daemon.py`
- `n = 20` in `estate.py:run_prospector` default candidates
- `[8s, 7s, 5s, 3s, 1s]` keep-awake ladder in `host.py`
- `DAILY_TASK_BUDGET = 80` somewhere in coordinator

Move to a single `~/.hermes/config.yaml` or `operator_shell/constants.py` so they're documented.

---

## 4. The Gap Map — what's missing for "seamless and heavenly"

### Already shipped (do not re-ship)

✅ Severity legend (panel_chrome.py)
✅ VERDICT_GLYPHS central source
✅ One-tap verbs (`*_now` suffix aliases)
✅ Loading indicator on tap
✅ Preflight probe cache
✅ Callback timeout guard
✅ Diff panel
✅ Daemon count on status
✅ Activity root-cause dedup
✅ Mission card breadcrumb
✅ Spend gauge with `[daily cap]` label

### P0 — ship next (operator UX is unusable without these)

| ID | Fix | Why now | Effort |
|----|-----|---------|--------|
| **P0-1** | Show full failure message inline on mission card (no truncation) | Operator sees the same alert 5× per day and can't act without 2 extra taps. U1, U8. | S (20 lines in `mission.py`) |
| **P0-2** | Mission card warm cache (avoid 6s re-render on every tap) | Mission card is the most-tapped panel. 6s × 10 taps/day = 60s wasted daily. | S (`preflight.py: cache 'refresh' too`) |
| **P0-3** | Prospector dedup: 3× same `paused:` skip → 1 root-cause line | Same defect activity panel got fixed (P0-4) but didn't reach prospector. U6. | S (re-use activity dedup helper) |
| **P0-4** | Prospector log "Recent log" — add absolute timestamp | User asked for this in context summary. U7. | XS (1 line) |
| **P0-5** | Daemon panel: inline glossary for `armed / fenced / calendar / interval / dirty` | Operator sees these daily and asked what they mean. U3, U4, U5. | S (text-only fix in `daemons.py`) |
| **P0-6** | `restart` confirm card: name the thing being restarted | "♻️ *Restart coordinator?*" ambiguous when many daemons exist. U11. | XS (1 line) |
| **P0-7** | "now" literal routes to `refresh` | Documented footer says "say `now` to force" but typing "now" hits unknown. U16. | XS (3 lines in `estate.py`) |

### P1 — month-one: "seamless"

| ID | Fix | Why | Effort |
|----|-----|-----|--------|
| **P1-1** | `system_fuel` toast matches content state | "Fuel" toast on a budget-trip is misleading. U10. | XS |
| **P1-2** | Last-edit timestamp on every panel, not just mission card | Audit trail — when did this panel last probe? U12. | S (helper in `panel_chrome.py`) |
| **P1-3** | Tap truncated failure text → full message inline | One-tap reachability for failures. Replaces "👁 Inspect" pattern. | M (handler + render) |
| **P1-4** | `/status` unified entry — aggregates daemon/cron/mission/spend into one card | 12 commands → 1 command + drill-ins. (Spec #6) | S (compose existing renders) |
| **P1-5** | Context-aware button bar (state → button set) | Spec #5 — buttons that disappear or appear based on state. | L (per-panel) |
| **P1-6** | Living progress message (single pinned message that updates) | Spec #2 — most ambitious, kills scroll. | XL (coordinator changes) |
| **P1-7** | Cron health: disabled jobs and last-errors surfaced | 5 disabled jobs nobody sees. | M (new `cron_health.py`) |
| **P1-8** | `st_status` warmup in background thread on gateway start | First-tap is 64s because it hits Stripe. Pre-warm at boot. | M (asyncio task) |

### P2 — medium-term

| ID | Fix | Why | Effort |
|----|-----|-----|--------|
| **P2-1** | `estate.py` god-file split into `estate/dispatch/` modules | Maintainability, testability, onboarding speed | L |
| **P2-2** | Morning/Evening digest — reduce main-DM noise | Spec #7 — cron output to dedicated topic, not main DM | L |
| **P2-3** | Daily self-reflection: "what shipped, what didn't" | Already a cron job at 6pm but output is unstructured | M |
| **P2-4** | Voice brief — speak the morning digest | Existing `voice_brief.py` is text-only | L (TTS integration) |
| **P2-5** | Per-verb usage analytics — which panels are tapped, how often | Data-driven UX iteration | M |

### P3 — longer-term / "heavenly"

- AI-driven panel composition (operator says "show me why signal engine failed" → panel synthesizes the answer)
- Haptic-style alerts (Telegram has limited support; could chain Telegram → ntfy → local notification)
- In-place approval flow on `/panel` (no drill-down to inbox)
- Auto-trust patterns: stop asking the operator to confirm things they've already approved

---

## 5. Recommendation — execution order

```
Week 1:  P0-1 → P0-2 → P0-3 → P0-4 → P0-5 → P0-6 → P0-7  (all small, daily impact)
Week 2:  P1-1 → P1-2 → P1-3 → P1-4 → P1-7  (consistency + dedup)
Week 3:  P1-5 (state-aware buttons) → P1-8 (background pre-warm)
Week 4:  P2-1 (god-file split) → P2-2 (digest routing)
Week 5+: P1-6 (living message) → P2-3/4 (voice + reflection)
```

**The "seamless" line is crossed after Week 1.** Median tap-to-action ≤2, mission card
≤1s warm, no truncated failures, no mystery jargon.

**The "heavenly" line is crossed after Week 4.** Operator never taps `/panel` —
`/status` covers it. Cron output doesn't bleed into main DM. Daemon panel reads like
prose. State-aware buttons predict what they'll need next.

---

## 6. Receipts & evidence

- `~/.hermes/hermes-agent/gateway/operator_shell/` — 31 files, 10,178 lines
- `~/.hermes/cron/jobs.json` — 23 jobs, 5 disabled with errors
- Live probe captured 2026-07-31 19:42 UTC, all panels, full output preserved
- Cold cache miss for `st_status` reproduced 5× in last hour (logs)
- P0/P1 batch receipts in `~/.hermes/specs/hermes-ui-improvements.md`
- Recent crash: full audit captured before fixing `preflight.py` untracked warning

---

## 7. Risks & non-goals

**Don't break:**
- `_finish()` idempotency contract — every action stores request_id → text
- `pin_edit=True` mission card edit semantics
- `_safe_callback_data()` 64-byte Telegram cap
- One-tap safety boundary: only idempotent ops get `_now` aliases

**Don't do:**
- Migrate to a UI framework — the cockpit IS Telegram, and Telegram is the phone UX
- Build a dashboard webapp unless the founder asks — `streamlit` exists but isn't used daily
- Add a "settings" panel — config goes in `config.yaml`, not in chat
- Auto-decide anything that moves money (must stay ARM-confirmed)

**Won't fix in this round:**
- Pre-existing Telegram API slowness (network, not our code)
- Signal Engine stability (separate workstream)
- Prospector `zero_yield` (gate tuning problem, not UI)
- Founder-grant prompts (Full Disk Access — needs out-of-band action)