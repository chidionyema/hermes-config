# Cockpit Deep Audit — 2026-08-01

> Methodology: Every claim below was verified by reading the actual file (path:line) or running
> an actual command. Inferences are marked `[INFERRED]`. No claims from memory; no opinions
> without evidence. This audit is descriptive — fixes are proposed in §10, ranked by impact,
> but not implemented here.

**Scope:** the Telegram-facing operator cockpit — the "🎛 Cockpit" pinned card, the
`/panel`, `/status`, `/fleet`, `/inbox`, `/missions`, `/brief`, `/cron`, `/busy`, `/notify`,
`/revert`, `/help`, `/sethome` slash commands, and every button reachable through them.

**Code surface audited:** 22 modules under `~/.hermes/hermes-agent/gateway/operator_shell/`
+ `gateway/slash_commands.py` + `gateway/platforms/telegram.py` callback handlers.

**Modules by size (lines of Python):**

| Module | LoC | Purpose |
|---|---:|---|
| `estate.py` | 1,351 | Dispatcher (1100-line if/elif) + cache + record + `render_panel_view()` |
| `signal_engine.py` | 1,007 | Money rail — start/stop/ARM + 29 params + TCC honesty |
| `prospector_daemon.py` | 995 | Idea generator — pause/run_now + cluster dedup |
| `cockpit.py` | 671 | Run (verbs) + Tune (knobs) + Activity (audit) |
| `daemons.py` | 599 | launchd health + restart verbs |
| `mission.py` | 488 | Home card ("🎛 Cockpit · …") |
| `code_remote.py` | 470 | Code-run task cards |
| `natural_ops.py` | 336 | NL → callback vocabulary (the source `find` indexes) |
| `host.py` | 333 | Keep-awake / TCC / power |
| `atlas.py` | 315 | Browse: Money · Code · Machine · Brain |
| `panel_chrome.py` | 303 | The spine + Group/compose + clip + LEGEND |
| `activity.py` | 272 | Rolling audit log + `recent_knob_keys()` |
| `rsi_panel.py` | 258 | RSI sub-panel |
| `builds.py` | 246 | CI/builds |
| `fleet.py` | 229 | Repo list |
| `find.py` | 226 | Search across 131 destinations |
| `status_summary.py` | 229 | `/status` one-tap summary |
| `preflight.py` | 211 | 5s cache for hot panels |
| `delivery.py` | ~200 | Cron topic wiring |
| `brain.py` | ~180 | Model picker |
| `inbox.py` | ~170 | Awaiting-approval fences |
| **Total** | **~10,800** | One cohesive surface |

---

## 1. What is working well (cite-file:cite-line)

The cockpit is already the product of significant intentional design. The audit's first
job is to be honest about that, so we don't tear down what is actually load-bearing.

### 1.1 The IA spine — one nav row, enforced

`panel_chrome.nav()` (`panel_chrome.py:74-108`) emits exactly four buttons in fixed order:

```
⚡️ Now   🎛 Run   ⚙️ Tune   🔎 [+ 🔄 if not already there]
```

Every panel appends it via `compose()` or `with_nav()` (`panel_chrome.py:147-153`, `206-247`).
Before this existed, 13 panel modules built 26 distinct navigation rows — `Mission` sat
at index 0, 1, or 2 depending on which panel you were on, and four rows omitted it
entirely (`panel_chrome.py:1-24`). The module-level docstring reads as a measured
before/after — the fix is documented, not just done.

This is the cockpit's strongest structural asset. Everything below builds on it.

### 1.2 Text and grid cannot drift

`Group()` + `compose()` (`panel_chrome.py:156-247`) tie the message body to the button
grid so the legend never promises a control the grid lacks. A group with no live rows
emits no legend line. A run with 19 buttons became readable not because the buttons
were fewer, but because each row sat under its own labelled group, and the groups
matched the legend in the body (`cockpit.py:415-503`).

### 1.3 Money rail is honest about the dangerous states

`signal_engine.py:_VERDICT_WORD` (`:292-299`) distinguishes `tcc_denied`, `down`,
`stalled`, `unsupervised`, `not_installed` from `idle`. TCC denial (`EX_CONFIG(78)`)
gets its own handling (`:540-565`) — when the engine can't trade because TCC revoked
the entitlement, the panel says so in plain English, not "⚙️ idle". This is the right
kind of honesty for a money rail.

ARM flow is two-tap on purpose: `arm_card()` (`:722-813`) requires the operator to
confirm twice, with live equity and killswitch visible on the second screen. A button
that can move real capital should not be one tap.

### 1.4 Home card shows only what needs the operator

`mission.py:_concerns()` (`:240-343`) builds a concern ladder with explicit priority:
money/identity fences first, then circuit-breaker open, then awaiting decisions, then
blocked missions, then code runs, then budget/degraded. The home renders at most 2
(`_MAX_CONCERNS = 2`, `:361`), with `+N more in Inbox / Run` (`:464-465`). Quiet days
show the spine and Pause only — no destination mall (`:386-388`).

### 1.5 Find is derived, not hand-kept

`find.py:_index()` (`:81-99`) derives its 131-destination index from
`natural_ops._PATTERNS` — the regex literals *are* the vocabulary. A new op is findable
the moment it is added; the second list cannot drift. Slash commands are pulled from
the same registry (`find.py:102-129`). Empty Find falls through to Atlas rooms
(`find.py:185-188`) — typing nothing is "browse", typing is "search".

### 1.6 Failure clustering in Activity

`cockpit.py:_group_failures_by_root_cause` (`:506-577`) clusters failures within a
30-second window with the same action prefix — one botched prompt-suggestion shows as
one cluster, not six noisy lines. Failures lead the Activity panel, with synthetic
probes explicitly labelled so the operator never trusts a number that includes
test rows.

### 1.7 Pre-flight cache on the hot path

`estate.py:198-244` caches `refresh`, `st_status`, `st_health`, `st_reconcile`,
`st_money`, `builds` for 5 seconds. The mission card is the most-tapped panel
(claimed ~10× any other) and its cold path was 6s. Cached tap is instant;
background refresh fires so the next tap is fresh. Mutating actions never use
the cache — staleness there is a real bug.

### 1.8 Idempotency on the dispatcher

`handle_estate_action()` (`:174-243`) records every action with a `request_id`,
checks idempotency before dispatch, and replays the prior `text`/`buttons` if the
same request_id reappears. Telegram retries are real; this is the right defensive
shape.

### 1.9 Record-on-everything

`activity.record()` is wrapped around `_dispatch` so even raises are audited
(`estate.py:226-243`). A raise is exactly the outcome worth auditing — recording
only successes hides the failure modes.

### 1.10 Cron delivery honesty

`delivery.py:cron_delivery_state()` is read live during render (`cockpit.py:221-233`)
— the home card offers `🗓 Fix cron delivery` only when the probe says it's broken,
and Tune always shows the current delivery label. Never a guess.

---

## 2. The home card — what you actually see

`render_panel_view()` (`estate.py:150-171`) → `render_mission_card()` (`mission.py:411`).

```
🎛 Cockpit · <verdict> — <detail>

<R S I>  🔥 <spend_today>     ⏸ / ▶ Pause

<FIX 1 — full-width>          <-- at most 2
<FIX 2 — full-width>

🗓 Fix cron delivery (only if delivery is broken; never otherwise)

⚡️ Now  🎛 Run  ⚙️ Tune  🔎 [+ 🔄]
```

`_verdict()` (`mission.py:69-118`) returns one of nine states, with explicit
priorities (paused > degraded > budget > CB > blocked > busy > degraded > clear).
Never 🟢 CLEAR when anything is blocked, busy, or down — the docstring rule
(`mission.py:1-4`).

`_concerns()` (`:240-343`) is the priority ladder the home reads from. Money/identity
fences come first — even when they were `escalated` (previously invisible), now
both `awaiting_approval` and `escalated` are surfaced for one-tap approve.

**This is genuinely first-class work.** The home card is the product.

---

## 3. The IA — three containers, 131 destinations

The spine `⚡️ / 🎛 / ⚙️ / 🔎` maps to four containers:

| Container | Reads | Writes | Lines | Density rule |
|---|---|---|---:|---|
| ⚡️ Now (home) | Estate state, verdict, spend | Pause/Resume, 2 fixes | ~120 | Hard cap 2 fixes |
| 🎛 Run | State of daemons, engines | All verbs (~19) | ~165 | Max 3 rows per group |
| ⚙️ Tune | Knob current values | All knob setters (~29) | ~225 | Max 9 buttons per group; recent promoted to home |
| 🔎 Find | Atlas rooms + search | Search-driven dispatch | ~80 | Result cap 8 (find.py:179) |

This is documented intent (`panel_chrome.py:32-48`, `cockpit.py:1-24`):

> Configuration outnumbered everything the operator actually does, 45 to ~10, and it
> won the real estate: `se_params` rendered 28 buttons on one phone screen. Yet that
> same screen was INCOMPLETE — 6 of the 29 allowlisted values had no button.

The split was the right fix. Before, Run and Tune were interleaved and a 28-button
`se_params` had 6 unreachable allowlisted values. Now Run is verbs, Tune is knobs,
and the 6 missing values are all present (`cockpit.py:88-93`, `113-117`).

---

## 4. Per-panel audit

### 4.1 ⚡️ Now (mission card, `mission.py`)

**Strong.** Verdict ladder is correct. Concerns ladder is correct (money/identity
first). Cap of 2 is honest. Quiet day is genuinely quiet — spine + Pause only.
**Minor:** the `_SURFACES` 3×3 destination mall at `mission.py:355-359` is dead code
(kept for tests per the comment `:354`), but it is still defined, still imports its
callbacks, and a grep for it would lead a maintainer to a panel that no longer
exists. Delete or move to `tests/`.

### 4.2 🎛 Run (`cockpit.py:415-503`)

**Strong.** Five labelled groups with state predicates — buttons appear only when
they can do something. `_safe()` wrapper (`cockpit.py:370-374`) means a probe that
fails renders BOTH Pause and Resume rather than guessing — a wrong guess here either
silently burns or silently halts the estate (`cockpit.py:439-442`). Restart and run_now
execute immediately; stop/start still confirm. The whole predicate-on-every-button
pattern is the right shape for verbs.

### 4.3 ⚙️ Tune (`cockpit.py:272-362`)

**Strong.** 5 groups × ≤9 buttons. Recently-touched knobs promoted to the home of
Tune (`cockpit.py:300-318`) so the ones with traffic are 2 taps, not 3. `current`
value is printed beside every button row, `?` on probe failure (`:256-269`).

**Note:** the recently-touched promotion is a clean self-calibrating system — the
knobs you actually touch move up, the ones you don't stay in their group. This is
the kind of micro-decision that elevates the experience.

### 4.4 🔎 Find / Atlas (`find.py`, `atlas.py`)

**Strong intent, sharp edge.** Find is derived, indexed against 131 destinations,
capped at 8 results with no pagination (`find.py:179`). For a query that matches
many destinations, the cap hides the rest. Atlas has 4 rooms (Money / Code /
Machine / Brain) with state probes. Empty Find = Atlas (`find.py:185-188`).

**Friction:** typing `restart` matches more than 8 things, and there is no
"see more". The user discovers this only when they expect a hit and don't see it.

### 4.5 Signal Engine (`signal_engine.py`)

**The strongest panel for the most dangerous state.** Two-tier ARM, live equity
on confirm, `_VERDICT_WORD` distinguishes the dangerous states. The TCC denial
case is first-class. The 29 `_SAFE_PARAMS` allowlist (`:330-391`) is the safety
boundary on the money rail.

**Friction:** `se_params` is now a stub (`:679-718`) — the setters migrated to
Tune, but the callback `estate:se_params` still exists and every Knobs button in
the panel still points at it (`signal_engine.py:727, 732, 739, 755, 767, 777, 782,
811, 830`). A reader who follows those buttons lands on a dead-end screen that
links back to Tune. Either rewire the buttons to `estate:tune:exec`, `estate:tune:
sizing`, etc., or mark `se_params` as deprecated and redirect.

### 4.6 Prospector (`prospector_daemon.py`)

**Strong.** Pause vs unpause logic is correct (`:465-476` of `cockpit.py` references
the file's labels — `pd_unpause` is the right verb, not `pd_run_now` which leaves
PAUSE in place). Cluster dedup of skip reasons (`:574-606`). Render functions are
state-aware.

### 4.7 Daemons (`daemons.py`)

**Largely strong.** KeepAlive vs interval/calendar distinction (`:228-250`) is
correct. Restart verbs correctly detached (`:503-536`).

**Footgun:** `estate:daemon_stop:coordinator` is exposed (`:386`) but stopping
the gateway from itself is refused at runtime (`:550-556`). A button that doesn't
work teaches the operator that taps are unreliable. Remove the button or wire the
guard into the render predicate.

### 4.8 Fleet (`fleet.py`)

**Mixed.** Uses severity correctly for `state == "fail"` only (`:157-167`), not for
`dirty()`. Severity glyph is right for clear failure but ignores the dirty case.

### 4.9 Inbox (`inbox.py`)

**Strong on priority.** Money/identity/contract fences ordered first
(`mission.py:135-146`). Approve is one tap from home — never a detour through
Inbox just to approve.

### 4.10 Activity (`cockpit.py:580-671`)

**Strong.** Failures lead, with root-cause clustering. Synthetic rows explicitly
labelled. Windows offered for 24h / 7d / 30d, omitting the current one to avoid the
duplicate-button defect (`:660-666`). Slowest section exposes latency regressions.

### 4.11 Brain (`brain.py`)

**Small but present.** Picker for current model.

### 4.12 Host (`host.py`)

**Currently orphaned.** `[INFERRED]` — `grep -rn "estate:host"` returns nothing
besides the Run row in `cockpit.py:496`. 331 lines of keep-awake / TCC / power
controls had no inbound button anywhere in the cockpit. The Run panel was the
first surface to expose Host; before that, it was reachable only by typing the
right phrase. Good catch.

### 4.13 Atlas (`atlas.py`)

**Strong.** 4 rooms with state probes. `find` falls through to Atlas on empty
query. Sub-rooms (e.g. `render_code_prompt`) exist for deeper inspection.

### 4.14 Status Summary (`status_summary.py`)

**Built — and is the `/status` slash command.** 229 lines, with spend gauge
(visual ▓░ bars, color by threshold), daemon/cron/mission counts, escalated
list, active list, orphans list. Solid.

### 4.15 Inbox (`inbox.py`)

Strong fences. See §4.9.

### 4.16 Panel Chrome (`panel_chrome.py`)

The spine. The invariant. Everything good about this cockpit flows from here.

---

## 5. Friction points (ranked)

> Section 5.0 (this version) folds the session-mined pain from
> `~/.hermes/reports/cockpit-friction-mining-2026-08-01.md` into the static audit.
> Every friction event below has a `session_id:msg_id` receipt and a code
> `file:line` citation. The two layers of evidence are independent: the code is
> read from disk, the pain is read from sessions.db.

### 5.0 The user-side pain (top 5, mined from sessions)

From `~/.hermes/reports/cockpit-friction-mining-2026-08-01.md`:

| # | Pain | Receipt | Code locus |
|---|---|---|---|
| 1 | Mission card truncates with `…` — "🧱 BLOCKED c1d2a4dd failure: Signal Engine daemon…" — full message stored, hidden by render | `20260731_210440_3ffb6c:8728` | `mission.py:240-280` (the row builder) |
| 2 | Cold mission-card re-render = 6,307 ms — 10× slower than the next-worst panel (fleet 1,352 ms). 60s/day wasted at 10 taps | `20260731_210440_3ffb6c:8732` | `estate.py:198-244` (cache wrapper) — fixed 2026-07-31 |
| 3 | 5 cron jobs sitting disabled with `last_status=error` — invisible from `/cron` because the panel filters out disabled jobs by construction | `20260621_100716_2e2c465d:5214` + `20260731_210440_3ffb6c:8732` | `status_summary.py:76-85` (the orphans helper exists but is only rendered on `/status`) |
| 4 | "Where is D?" — 3-word recall hits clarifying questions, not the existing `session_search` tool | `20260710_211203_c2d4801a:7202`, `20260621_100716_2e2c465d:5215`, `20260624_023255_73d015f9:5726` | no `/find <token>` slash command exists |
| 5 | Typing `now` (which the footer literally tells the operator to type) hit `⚠️ Unknown action now` | `20260731_210440_3ffb6c:8732` | `estate.py:1622` (then) → `estate.py:181-183` (alias resolved) — fixed |

User pain quotes (verbatim, cited):

> **"This doesn't have timestamps"** — `20260731_210440_3ffb6c:8709`, repeated at `:9019`
> **"Where is D?"** — `20260710_211203_c2d4801a:7202` (three words, no glossary, expects recall)
> **"Where is your self audit"** — `20260621_100716_2e2c465d:5215` (the second `where is` query in 48h)
> **"Ok you need to wrap this up"** — `20260731_211736_09fa32:9247` (user expected the session to *finish its own work*, not ask to stop)
> **"I think we can skip the refactoring and get the others done"** — `20260731_210440_3ffb6c:9018`, `:9021` (operator had to use calm-override *twice in one session*)

Recurring patterns the mining identified:

- **Pattern A — "I can see there is something, but I cannot see what"** (hidden-state surface). The verdict glyph + short string on every panel expects the user to drill down. Repeats across `mission.py`, `fleet.py`, `daemons.py`, `prospector_daemon.py`.
- **Pattern B — "The thing I want to do is documented but doesn't actually work"** (broken affordance). The `now` alias is the canonical case. The reflect-on-correction spam is the prescribed-but-not-shipped case (audit 06-20 → re-prescribed 06-21 → still broken 06-22).
- **Pattern C — "Same error spammed into the same channel"** (anti-dedup at the source). 12 identical reflection blocks in 4h; 131 watchdog re-fires on 2 overnight errors.
- **Pattern D — "I told you what to read, but you didn't"** (cross-session amnesia). "Where is X?" — the internal `session_search` tool already answers; the operator has to know to ask for it.
- **Pattern E — "Discovery via raw 12-command list"** (no `/help` worth reading). The Telegram menu still ships 12 commands with no curation.

The full friction-mining report is at `~/.hermes/reports/cockpit-friction-mining-2026-08-01.md` (542 lines, 40.8 KB) with per-event reading-context snapshots, joy moments, and capability blind spots.

### P0 — Blocks operator capability or teaches wrong expectations

**F1. `se_params` is a dead-end panel**
- `signal_engine.py:679-718` — `render_params()` now returns a stub "all knobs
  moved to Tune" screen.
- Every "💰 Knobs" button in `signal_engine.py` still calls `estate:se_params`
  (`:727, 732, 739, 755, 767, 777, 782, 811, 830` — 9 call sites).
- A thumb following those buttons lands on the stub, not the setters.
- **Fix:** rewire those buttons to `estate:tune:exec|sizing|safety|spend` based
  on the parameter. One-line changes; preserves the affordance.

**F2. `estate:daemon_stop:coordinator` is a button that doesn't work**
- `daemons.py:386` — exposed in the daemons row.
- Runtime refuses to stop the gateway from itself (`:550-556`).
- **Fix:** drop the button. Restart is the safe verb; stop-from-self is not.

**F3. The 1100-line `_dispatch` if/elif chain**
- `estate.py:263-1325` — every new estate action must be added here.
- Branch-by-branch growth is the wrong container once it crosses ~500 lines.
- **Fix (medium):** extract a dispatch table — `dict[action, Callable[..., PanelView]]`.
  Idempotency wrapper + recording wrapper stay in `handle_estate_action`. This is a
  pure refactor; no behavior change.

### P1 — Causes friction or hides capabilities

**F4. `_SURFACES` 3×3 destination mall is dead code**
- `mission.py:355-359` — kept "for tests" per comment `:354`.
- Still defines 9 callbacks. A future maintainer who grep'd for these would find
  them and assume they render.
- **Fix:** move to `tests/` or delete. Add a comment that home does not render it.

**F5. `find` cap of 8 with no pagination**
- `find.py:179` — search returns at most 8 hits, no "see more".
- A query like `restart` matches many destinations and silently truncates.
- **Fix (small):** add `estate:find_more:<query>` returning the next 8.

**F6. Some panels emit their own nav row instead of `with_nav`**
- `fleet.py:186`, `daemons.py:388`, `prospector_daemon.py:784`, `atlas.py:172` —
  each builds its own nav row.
- Drift risk: the spine changes (it has, once already — `🔎` was added late),
  and panels that maintain their own copy go stale silently.
- **Fix (small):** grep for `("🎛 Run", "estate:run")` and `("⚙️ Tune", "estate:tune")`
  — every match should be replaced with `nav(...)`.

**F7. Callback-data 64-byte truncation is silent**
- `gateway/platforms/telegram.py:33-50` — `_safe_callback_data` truncates with a
  log line, but the operator only sees the log; the button silently fails.
- **Fix (small):** surface the truncation in the panel toast — "Button truncated;
  open `/panel` to reach this control." Toast is a free channel.

**F8. Empty-state ambiguity for Find**
- `find.py:192-200` — `🔎 Nothing matches *foo*.` is correct, but it doesn't say
  *what kinds of words* work. The stopword list (`find.py:30-38`) silently
  drops 60+ words.
- **Fix (small):** when the query is all stopwords, say so: "Those are stopwords;
  try a noun (restart, spend, model)."

### P2 — Polish / delight

**F9. Severity gauge for `dirty` is missing in Fleet**
- `fleet.py:157-167` — only `state == "fail"` flips the glyph.
- **Fix (small):** mirror the dirty() check from panel_chrome LEGEND.

**F10. The home "primary CTA" falls back to "🚀 Fleet"**
- `mission.py:346-349` — when there are no concerns, primary is Fleet.
- But on a quiet day, the comment at `:386-388` drops it.
- **Fix (cosmetic):** consider "📜 Activity" or "🌅 Brief" as quiet-day primary
  — something the operator genuinely wants to glance at, not a destination
  they didn't ask to visit.

**F11. No top-level `/brief` button on the home**
- `/brief` exists and renders `voice_brief.render_executive_brief()` (called
  from `estate.py:488-499`).
- But the home card never offers it. The morning/evening digest pattern
  (`hermes-ui-improvements.md:213-247`) is spec'd but not built.
- **Fix (medium):** add digest delivery to cron; add a one-tap digest button on
  home for off-schedule reads.

**F12. `/notify` and `/busy` and `/revert` and `/sethome` exist but I can't
find them in the rendered cockpit**
- They are in the 12-command Telegram menu (`menu.py:9-22`) but not surfaced
  on any panel as buttons.
- `/find` indexes them (`find.py:102-129`), so they are discoverable by search.
- **Fix (small):** each is a niche verb — `/busy` (set myself busy), `/revert`
  (undo last). They could live on a small "Settings" spine position, or stay
  findable. Decision needed.

---

## 6. Cryptic patterns (require explanation)

| Pattern | Where | Why cryptic |
|---|---|---|
| `say now to force` footer | mission card | Word "now" means "re-render this card" — not the literal English word |
| `estate:now` doesn't exist | alias resolved at `estate.py:181-183` | Typing `now` had to be re-aliased after the cache refactor |
| `⌨️ type X` lines in Find | `find.py:206-214` | Operator can read "type X" but X is sometimes wrong: `find.py:71-74` explicitly notes that the action name is *not* it |
| `estate:` callback prefix | every button | Telegram convention, but unexplained on first contact |
| 64-byte callback_data cap | telegram.py:30 | Invisible to operator; surfaces only when it bites |
| `_SURFACES` mall | dead, but still grep-able | Reads as if home renders a destination grid |
| `?` glyph in current-value rows | cockpit.py:260-268 | Means "probe failed" — never a guess, but the operator has to learn it |
| The "🟢 / 🟡 / 🔴 / ⚠️" legend | panel_chrome.py:59 | Appears on every panel — good — but is the only place the operator learns ⚠️ ≠ 🟢 |

The legend on every panel (`panel_chrome.py:59`) is the right shape for this. It
appears, it stays short, and the most common question (green vs amber vs red) is
answered on first glance.

---

## 7. Joyless patterns (works but feels like a chore)

| Pattern | Where | What makes it feel like work |
|---|---|---|
| Opening `/panel` and seeing 0 fixes when everything is fine | mission.py:386-388 | Correct, but the operator gets nothing to do — could surface a small "today" line (e.g. today's decisions, today's spend, last cron summary) |
| Typing a slash command and getting "Unknown action" | `estate.py:174-181` | "Now" was the specific case; many other reasonable phrasings hit this |
| `+N more in Inbox / Run` | mission.py:464-465 | Tells you there are more, but doesn't take you there |
| Reading a clipped mission name with `…` | was `clip(..., 28)` in older mission.py | Now uses full title (`mission.py:200-204`) — this is the recent fix |
| The orphan-cron list on `/status` | status_summary.py:192-201 | Useful but the line `"…+N more — /cron list --all"` references a CLI flag that may not exist as a slash command |

---

## 8. Joy moments (preserve in the redesign)

These are patterns that already delight. Don't lose them.

1. **Recently-touched knob promotion** (`cockpit.py:300-318`) — the knobs you use
   come to you. Self-calibrating, no config.

2. **Predicate-on-every-button** (`cockpit.py:415-503`) — no "▶️ Start" for
   something already running. The button you see is the button that does something.

3. **Concern ladder priority** (`mission.py:240-343`) — money/identity/contract
   fences first, always. The home does not bury a money approval under housekeeping.

4. **Cluster dedup of failures** (`cockpit.py:506-577`) — one botched prompt
   suggestion is one bug, not six noisy lines.

5. **"Telegram wraps long lines"** (`mission.py:200-204`) — the recent fix to
   print full mission names instead of clipped ones. Wrapping is a phone-feature,
   not a defect.

6. **`🔄` is a smart button** (`panel_chrome.py:99-108`) — only appears when it's
   not already a callback elsewhere on the row. No accidental duplicates.

7. **The legend on every panel** (`panel_chrome.py:59`) — one row, always
   present, never redrawn per panel.

8. **The `⚠️ unproven` glyph distinct from green** (`panel_chrome.py:66-71`) —
   never pretend to know what you don't. The whole document culture around this
   is consistent.

---

## 9. Navigation graph (BFS)

`[INFERRED — measured by the IA docstrings, not by a fresh BFS run.]`

| Destination | Taps from home | Notes |
|---|---:|---|
| ⚡️ Now (home) | 0 | |
| 🚀 Fleet | 1 | from home or Run |
| 📥 Inbox | 1 | from home concerns or Run |
| 🎛 Run | 1 | spine |
| ⚙️ Tune | 1 | spine |
| 🔎 Find / Atlas | 1 | spine |
| A specific knob group (e.g. Sizing) | 2 | Tune → group |
| A specific knob value (e.g. lev 2x) | 3 | Tune → group → value (unless recently-touched, then 2) |
| Daemons panel | 1 | from Run |
| Host panel | 1 | from Run (since the recent fix) |
| Brain panel | 1 | from Tune |
| Brief / Morning digest | 1 (command) or 2 (panel→brief) | exists but not surfaced on home |

This is healthy. Most verbs are 1 tap; configuration is 2-3 taps; search is
always 1 tap away.

---

## 10. Top 10 recommendations (with effort + impact)

Re-ranked after session-mining (Pattern A through E from §5.0). The top three
are now user-evidenced, not just code-evidenced.

| # | Recommendation | Effort | Impact | Evidence |
|---|---|---|---|---|
| 1 | Ship `/find <token>` slash command — wraps `session_search()` to render a 1-screen answer for free-text recall | S | **Critical** | Pattern D — 3 sessions in 60 days where "where is X?" hit clarifying questions instead of a lookup. Already 70% built (the tool exists; the slash command is missing). |
| 2 | Surface disabled-with-errors cron jobs on `/cron` and on `/status` (already partially built — `status_summary.py:_cron_orphans` exists, just not on `/cron`) | S | **High** | Pattern A + the 5 orphaned jobs cited in `20260621_100716_2e2c465d:5214` |
| 3 | Stop truncating mission-card blocker rows with `…` — print full stored message inline | S | **High** | Pattern A — `20260731_210440_3ffb6c:8728` shows the truncation is a render decision, not a layout constraint |
| 4 | Rewire `estate:se_params` → `estate:tune:<group>` in `signal_engine.py` (9 call sites) | S | High | Code-evidenced dead-end |
| 5 | Drop `estate:daemon_stop:coordinator` from `daemons.py` button bar | S | High | Code-evidenced footgun |
| 6 | Refactor 1100-line `_dispatch` if/elif chain into dispatch table | M | High | Code-evidenced scale problem |
| 7 | Add source-level dedup to `reflect-on-correction.py` and cron watchdog — diff-before-write + once-per-error-class-per-window | M | High | Pattern C — 12 identical blocks / 131 spam lines cited at `cron_85385abb646d_20260622_080926:5373` |
| 8 | Build a `/help` worth reading — curated, contextual, not a 12-line wall. The current menu is the same list it has been since June | S | High | Pattern E |
| 9 | Tap-to-expand inline failure text on Mission card + add `📐 receipts →` button per verdict row (Receipt-first panel mode from the joy moments) | M | Med | Pattern A + Joy #1 (war-room receipts) |
| 10 | Add a quiet-day "today" line to home card (decisions count, last cron summary) | S | Med | Sub-pattern of A — quiet home offers no signal today |

**Effort scale:** S = <1h, M = 1-3h, L = >3h.

**Joy-preservation list (do not lose when shipping the above):**

From `cockpit-friction-mining-2026-08-01.md §Joy Moments`:

- **War-room advisor concurrency** — 4 advisors render in 7–16s, chair-brief synthesises the disagreement honestly. The cockpit version of this is the "ask 4 advisors" verb, currently invisible.
- **"Perfect — there's a test pattern I can follow"** — the codebase often already solved the problem. The cockpit can expose this through Receipt-first panel mode.
- **The Fable of the Observatory** — the agent refused to invent a 3-word prompt's answer and wrote a 42-line fable about the failure mode itself. This is what honest no-action looks like; the cockpit should reward "I'm not sure" the same way (not pretend-🟢-when-unproven).

---

## 11. Honest assessment

The cockpit is well-engineered. The IA spine is enforced. Money rails are honest.
Concerns ladder is correct. Failure modes are clustered. Pre-flight cache kills
the cold-tap latency. Idempotency wrapper is right. The dead-code surface area
(`_SURFACES`, dead `se_params`) and the footgun surface (`daemon_stop:coordinator`)
are the obvious next code fixes; everything else is polish.

The session-mining layer changes the priority order. **Pattern D (`/find <token>`)
is the highest-leverage unmined lever** — three confirmed operator incidents in
60 days, and the underlying `session_search` tool already exists. Pattern C
(source-level dedup) would erase 131-line spam storms overnight. Pattern A
(hidden-state surface) is what makes the mission card feel like an evasion
instead of a dashboard.

The user's brief — "world class, elegantly and creatively guides and exposes all
its capabilities without overwhelming, navigation first class, delightful" —
maps to three concrete levers:

1. **Expose what exists.** `/find <token>` + cron orphans on `/cron` + receipts
   button per verdict row. No new infra; just surface the substrate.
2. **Fix the broken affordances.** Stop truncating blocker rows, drop the
   no-op button, rewire the dead-end panel. 5 small fixes.
3. **Reward honesty over noise.** Source-level dedup so silent channels stay
   silent. Receipt-first panel mode so a 🟢 you can audit is worth more than a
   🟢 you can't.

The first item alone (a `/find <token>` slash command that wraps the existing
`session_search` tool) is ~50 lines and would have prevented every "Where is
X?" clarifying-question loop in the past two months.

---

## 12. Sources

- All operator_shell modules under `~/.hermes/hermes-agent/gateway/operator_shell/`
- `~/.hermes/hermes-agent/gateway/slash_commands.py`
- `~/.hermes/hermes-agent/gateway/platforms/telegram.py` (callback handling, `telegram.py:33-50, 4303+`)
- `~/.hermes/specs/hermes-ui-improvements.md` (the prior spec)
- `~/.hermes/specs/otto-cockpit-audit-2026-07-31.md` (the prior audit doc the friction-mining report cites)
- `~/.hermes/hermes-agent/tests/gateway/operator_shell/` (`test_cockpit_ia.py`, `test_cockpit_activity.py`, `test_panel_smoke.py`)
- `~/.hermes/cron/jobs.json` (cron delivery wiring)
- **`~/.hermes/reports/cockpit-friction-mining-2026-08-01.md`** — the parallel session-mining pass (542 lines, 40.8 KB) that produced §5.0
- Direct `session_search` calls against `~/.hermes/sessions.db` for the 6 sessions cited in the mining report

**Known gaps in this audit:**

- A live BFS measurement of tap-depth across all 131 destinations (claimed from
  the IA docstrings, not measured here).
- The full `signal_engine.py:679-830` was read but not exhaustively audited
  beyond the `se_params` dead-end and `_VERDICT_WORD` honesty — the 1007-line
  module likely has more dead affordances of the same shape.
- `voice_brief.py`, `notify_fanout.py`, `rsi_panel.py`, `code_remote.py`,
  `chat_router.py`, `cron_ops.py` were inventoried but not read end-to-end.
  Each has its own render function and its own potential dead-code surface.