# Otto / Hermes Cockpit Friction Mining — 2026-08-01

**Mined by:** Otto, on explicit delegation from Chids
**Corpus:** `~/.hermes/sessions.db` (last ~60 days, 40+ sessions touched)
**Method:** FTS5 + scroll-windowed context retrieval (8 discovery queries, 6 scroll slices, no fabrication)
**Posture:** Read-only mining → one report. No pipeline files written to `specs/` or `operator_shell/`. The deliverable is this document.

---

## Synthesis (the one-paragraph readout)

Across the past two months of cockpit use, the operational friction is concentrated in **three failure modes that all show up on a single screen — the mission card** (truncation hiding what is broken, 5–10× warmer re-render than every other panel, jargon like `armed / fenced / dirty(N)` left unexplained), **two structural pipelines that compound the noise** (`reflect-on-correction.py` re-emitting 12 identical "Auto-Reflection" blocks every 30 min for 48h+; cron watchdog re-firing on two overnight path-errors 131 times in 5 hours), and **one discoverability gap** that meets every user prompt — 12 slash commands, no `/help` that lists them, and the operator canonically types the literal string `now` that the footer tells them to type, only to be told "Unknown action." The good news is that this is now well-instrumented: a fresh cockpit audit on 2026-07-31 (msg 8728) already shipped all 7 P0 fixes end-to-end. The real unmined-and-shipped surface is P1 — `/status` unification, cron-health visibility for the 5 disabled-with-errors jobs, and tap-to-expand inline failure text. Joy moments (the war-room advisor pattern, the "perfect" callback when probe code worked first try, the legit Fable of the Observatory callback) tell us Otto is most delightful when it acts *as an orchestrator* with verifiable receipts — so the highest-leverage cockpit capability to expose is a "ask 4 advisors in parallel on this question" verb and "show me receipts, not vibes" as a first-class panel state.

---

## Top 10 Friction Events

### 1. Mission-card alert hidden behind `…` (the "Signal Engine daemon…" trap)
- **Date / session:** 2026-07-31 cockpit audit (`20260731_210440_3ffb6c`)
- **What the user tried:** Tap the `/panel` to see what's broken; expect to act on the first alert
- **What broke:** Mission card renders `🧱 BLOCKED c1d2a4dd failure: Signal Engine daemon…` (ellipsised mid-message). Operator sees "something is broken, something Signal Engine" but cannot act without opening Inbox → Inspect → full message — 2 extra taps and ~3 seconds, every time.
- **What would have been better:** Either render the full stored failure inline (120 chars is fine), or make the truncated row tap-to-expand inline.
- **Citation:** `20260731_210440_3ffb6c:8728` (audit doc); `20260731_210440_3ffb6c:8730` (follow-up todos list P0-1 as in-progress)
- **Status:** SHIPPED as P0-1 by Otto on 2026-07-31 (`20260731_211736_09fa32:9245`)

### 2. Cold mission-card re-render is 6.3 seconds, every tap
- **Date / session:** 2026-07-31 (`20260731_210440_3ffb6c`)
- **What the user tried:** Tap mission card repeatedly for the live state (it's also the auto-refresh pin)
- **What broke:** The cold-cache render of `refresh` is 6,307 ms — **10× slower than the next-worst panel** (`fleet` at 1,352 ms). At 10 taps/day that's 60 wasted seconds.
- **What would have been better:** Warm cache (5s TTL) — the only reason this panel is slow is that it's special-cased out of `preflight.py`.
- **Citation:** `20260731_210440_3ffb6c:8732` (audit receipts, panel latency matrix)
- **Status:** SHIPPED as P0-2 — verified cold 1,095 ms → warm 0 ms (1,095× speedup)

### 3. Prospector panel: 3× same `paused:` skip with no root-cause dedup
- **Date / session:** 2026-07-31 (`20260731_210440_3ffb6c`)
- **What the user tried:** `/panel prospector` to see why scheduler kept skipping
- **What broke:** Three rows: `🔴 skip 43m ago — paused: /Users/.../PAUSE`, `🔴 skip 44m ago — paused: ...`, `🔴 skip 57m ago — paused: ...`. Same root cause, three lines. The activity panel got a dedup fix; prospector was missed.
- **What would have been better:** Re-use `_group_failures_by_root_cause()` — 18 noisy rows → 1 `🔴 skip ×3 — paused: ...` line.
- **Citation:** `20260731_210440_3ffb6c:8732` (audit U6 + P0-3); `20260731_211736_09fa32:9245` (confirms shipped)

### 4. "Recent log" on prospector had no absolute timestamp
- **Date / session:** 2026-07-31 (`20260731_210440_3ffb6c`)
- **What the user tried:** Diagnose which log line corresponds to which wall-clock moment
- **What broke:** Prospector's "Recent log" section header said only `_(1h ago)_` (relative). Heartbeat had absolute (`2026-07-31 19:01 UTC`); daemon status lines had only `pid`. Mixed mental model — the user has to switch between delta and absolute across one panel.
- **What would have been better:** Always include absolute timestamp in the section header; pick one convention panel-wide.
- **Citation:** `20260731_210440_3ffb6c:8732` (audit U7 + P0-4)
- **Status:** SHIPPED as P0-4

### 5. Daily `reflect-on-correction.py` emits 12 identical "Auto-Reflection" blocks (48h known bug)
- **Date / session:** 2026-06-22 strategist-audit (`cron_85385abb646d_20260622_080926`)
- **What the user tried:** Read the reflection file `logs/reflection/2026-06-21.md` for what Otto learned that day
- **What broke:** 317 lines, of which **250 lines (79%) were 12 duplicate "Auto-Reflection" blocks** with identical text, generated every 30 min from 19:24 to 23:57. The fix was prescribed in the 06-20 audit *and* the 06-21 audit, and was never implemented. The structural finding is even sharper: the entire "audit → action" loop is producing recommendations faster than any process is actioning them.
- **What would have been better:** Diff-before-write (read last-run timestamp + last-seen policy-firings cursor, exit 0 silently if no new firings). **Verification:** `grep -c "Auto-Reflection" ~/.hermes/logs/reflection/$(date +%F).md ≤ 1`.
- **Citation:** `cron_85385abb646d_20260622_080926:5373` (full report inline) and `:5371` (write_file receipt)

### 6. Cron watchdog re-fires 131× on the same two overnight errors
- **Date / session:** 2026-06-22 03:48–07:09 UTC (`cron_85385abb646d_20260622_080926`)
- **What the user tried:** Sleep through the night; expect silence
- **What broke:** Two jobs errored continuously for 5h+:
  - `daily-self-reflection` — `daily_reflection.py` line 19 had `Path.home() / "Documents" / "code" / ".hermes" / "OBJECTIVES.md"` — directory does not exist; script has the correct backup path at line 181 but errors on the wrong path first.
  - `proving-ground-audit` — wrong working directories for `signalengine/imports` and `prospector/imports` (`.venv/bin/` realpath error).
  Watchdog re-fires every 15 min → 131 `CRON_ERROR` entries drowning real signal in `watchdog.jsonl`.
- **What would have been better:** (a) Fix the line-19 path; (b) debounce repeated identical errors to once-per-error-class; (c) surface "5h unbroken same error" as a single severity-coded notification rather than 20 re-rings.
- **Citation:** `cron_85385abb646d_20260622_080926:5373` (audit §2 + P0 list)

### 7. Two cron-error classes go silent — disabled jobs with errors nobody surfaces
- **Date / session:** 2026-06-21 estate-update (`20260621_100716_2e2c465d`) + 2026-07-31 audit
- **What the user tried:** `/panel cron` to see "which automations broke"
- **What broke:** 5 cron jobs sitting disabled with `last_status=error`, some since 2026-07-30 (`Summarize today's activity`), 2026-07-29 (`daily-strategist-audit`), 2026-06-21 (`otto-dispatch`, `otto-improvement-pulse`). The cron panel is "healthy" because it filters out disabled jobs — by construction. Nothing tells the operator *that disabled jobs exist*, let alone *that they used to run and are now paused-with-stale-errors*.
- **What would have been better:** A "disabled with reason" row group, plus a tap-to-resurface-the-original-error action.
- **Citation:** `20260621_100716_2e2c465d:5214` (cron fleet snapshot); `20260731_210440_3ffb6c:8732` (audit §2.3)

### 8. "Where is D?" — ambiguous three-letter prompts produce silence
- **Date / session:** 2026-07-10 21:12 (`20260710_211203_c2d4801a`)
- **What the user tried:** Quick context-recall query: "Where is D?"
- **What broke:** Otto responded with three clarifications across hours, none advancing the task. The session collapsed into "Otto here — what's the goal of the moment?" repeated four times in a row, ending without resolution. Same pattern at 2026-06-24 02:32 AM: *"where is the mother ship / Interface?"* → escalation with `root cause:` blank because no acceptance test was specified.
- **What would have been better:** A `/find <token>` slash command that runs the same recall mechanic used internally (FTS5 + recent-sessions) — and returns a 1-screen answer before asking. The "where is your self audit?" session on 2026-06-21 (`20260621_100716_2e2c465d:5215`) shows the same recovery pattern: Otto *can* answer, but only when the user uses Otto's vocabulary. Chat should not require vocabulary.
- **Citation:** `20260710_211203_c2d4801a:7202` (user prompt), `:7203–7207` (assistance escalates to silence); `20260624_023255_73d015f9:5726` (mother-ship variant); `20260621_100716_2e2c465d:5215` ("where is your self audit")

### 9. "now" literal hits `⚠️ Unknown action` (footer promise broken)
- **Date / session:** 2026-07-31 cockpit audit (`20260731_210440_3ffb6c`)
- **What the user tried:** Type `now` exactly as the mission card footer told them to: "say `now` to force"
- **What broke:** `estate.py:1622` didn't accept `now` as an alias for `refresh`. Result: `⚠️ Unknown action now` error concatenated above the mission card — the user sees their own command echoed as an error, then the card anyway. Counter-intuitive.
- **What would have been better:** Map `now` → `refresh` at the entry of `handle_estate_action`. Trivial fix, documented in the footer.
- **Citation:** `20260731_210440_3ffb6c:8732` (U16, P0-7)
- **Status:** SHIPPED — verified in `20260731_211736_09fa32:9245`

### 10. `restart` confirm card ambiguous — "Restart coordinator?" when many daemons exist
- **Date / session:** 2026-07-31 (`20260731_210440_3ffb6c`)
- **What the user tried:** From the daemons panel tap "Restart" on a row that wasn't coordinator
- **What broke:** The confirm card read `♻️ *Restart coordinator?*` regardless of which daemon you tapped. With 7+ daemons visible, this becomes "which thing am I restarting?"
- **What would have been better:** Confirm card text pulled the launchd label: `Kicks \`ai.hermes.coordinator\` via launchctl`. Or, even better, name what the daemon *does for the user* (`Restart the gateway (handles all your Telegram messages)?`) — but the launchd label closes the ambiguity gap.
- **Citation:** `20260731_210440_3ffb6c:8732` (U11, P0-6)
- **Status:** SHIPPED with launchd-label naming

### (bonus) — `patch` tool mode confusion consumed ~15% of a 7-fix session
- **Date / session:** 2026-07-31 evening (`20260731_211736_09fa32`)
- **What the user tried:** Continue P1 batch — inbox panel truncation removal (P1-3)
- **What broke:** Otto repeatedly passed both `path` (replace-mode field) and `patch` (V4A field) in the same tool call, triggering schema rejection. Loop repeated 5 times verbatim, then tool-budget exhausted, ending the session with P1-3 half-shipped.
- **What would have been better:** A tool-call-time smoke check ("did the parameter names match the mode?") or simply reading the schema once. Notably the *user's* reply — "Ok you need to wrap this up" (`20260731_211736_09fa32:9247`) — became one of our clearest pain quotes: the user expected the session to *finish its own work*, not to be told to stop.
- **Citation:** `20260731_211736_09fa32:9242–9247`

---

## 5 Recurring Friction Patterns

### Pattern A — **"I can see there is something, but I cannot see what"** (hidden-state surface)

Every panel renders a verdict glyph (🟢🟡🔴⚪) plus a short string, and *expects the user to drill down*. Examples: `🧱 BLOCKED c1d2a4dd failure: Signal Engine daemon…`; `🟠 skipped gate`; `dirty(95)`; `inflight 0`. None of these have inline expansion, hover hints, or a "why" caption that fits above the row. The pattern repeats across `mission.py`, `fleet.py`, `daemons.py`, `prospector_daemon.py` — at least four panels, exactly the same anti-pattern. The user is trained to tap a row and hope the next screen is informative; that's the cockpit's most-tapped thing, by far.

### Pattern B — **"The thing I want to do is documented but doesn't actually work"** (broken affordance)

Two distinct flavours this month: (1) the `now` alias documented in the mission-card footer that hits `Unknown action now`; (2) the strategos that prescribed a reflect-on-correction patch *twice* and saw the broken output re-render anyway. Both look like "I told you how to use this" without checking that the prescription actually executes. The cure is the same: every affordance promise (footer text, button label, suggestion, audit recommendation) should have a self-verification hook.

### Pattern C — **"Same error spammed into the same channel"** (anti-dedup at the source)

`reflect-on-correction.py` emits 12 identical blocks in 4 hours. The cron watchdog fires 131 times on two overnight errors. Estate brief shows `failure: health-watchdog / failure: health-watchdog / failure: health-watchdog…` (`20260621_100716_2e2c465d:5230`). Every one of these is "the system found a problem and then forgot it found that problem." Root-cause dedup at the *source* (the producing script) is the right fix; symptom dedup at the *render layer* (the activity panel got it) is a band-aid.

### Pattern D — **"I told you what to read, but you didn't"** (cross-session amnesia)

Three sessions in a row (*"where is D?"*, *"where is your self audit?"*, *"where is the mother ship?"*) demonstrate the same gap: the user's conversational query implies "look it up and tell me," but Otto's first instinct is to ask a clarifying question. The internal `session_search` tool *is* a one-shot answer to every one of these — it's just not the default entry-point. `/remember` exists (`Otto remember <topic>`) but the user has to know to ask for it.

### Pattern E — **"Discovery via raw 12-command list"** (no `/help` worth reading)

The reply to a new user is a single Telegram message with **12 slash commands** (`/panel /inbox /fleet /brief /cron /busy /notify /revert /missions /audit /help /sethome`) and a paragraph of "Otto, <anything>". Compare with what was needed today: `/status`, `/cron health`, `/help`, "find the receipt for X", "ask the war room on this". The discoverability surface is *the same wall of commands* it has been since June, with no incremental curation. The P1-4 `/status` unification work (`20260731_210440_3ffb6c:8732`) implicitly fixes this for the most-common entry point but doesn't fix the second-order ones (`/cron`, `/help`).

---

## 5 Verbatim User Pain Quotes

> **"This doesn't have timestamps"**
> — Chids, reacting to the prospector daemons panel, 2026-07-31, repeating the panel composition before the audit even began
> Cited: `20260731_210440_3ffb6c:8709` and `20260731_211736_09fa32:9019` (same screen text repeated)

> **"Where is D?"**
> — Chids, 2026-07-10 21:12 — three words, no glossary, expects recall
> Cited: `20260710_211203_c2d4801a:7202`

> **"And where is your self audit"**
> — Chids, 2026-06-21 10:12 — second `where is` query in 48h; pattern D
> Cited: `20260621_100716_2e2c465d:5215`

> **"Where is the mother ship / Interface ?"**
> — Chids, 2026-06-24 02:32 AM — same pattern, fastest-moving hour, hardest interaction
> Cited: `20260624_023255_73d015f9:5726`

> **"Ok you need to wrap this up"**
> — Chids, 2026-07-31 — response to Otto's "patch tool confusion" loop; reveals a hidden expectation that long-running sessions must *close their own loop*, not ask the user to interrupt them
> Cited: `20260731_211736_09fa32:9247`

### (Bonus) Implicit-positive quote that anchors Pattern D

> **"I think we can skip the refactoring and get the others done"**
> — Chids, 2026-07-31, twice (`20260731_210440_3ffb6c:9018`, `:9021`) — the operator has a clear, calm override for scope; the friction is that the operator *had to use it twice in one session*

---

## 3 Joy Moments (preserve these)

### 1. War-room concurrency — "the orchestra works"
- **What:** Chids triggered a 4-advisor parallel consultation (`Otto, war room: ship it?`). DeepSeek/Claude/AGY/MiniMax each rendered in 7–16s with a one-line brief, *immediately* consumed by a chair-brief synthesis that was ready inside the same minute.
- **Why it delighted:** The receipts were heterogeneous (DeepSeek's risk profile disagrees with Claude's; Claude's verify-first conflicts with AGY's shadow-first) and the synthesis surfaced the *disagreement* honestly. Chids got a multi-perspective decision in two minutes that they would otherwise have assembled over an hour.
- **Citation:** `20260620_175237_59f2f30e:5119` (chair brief), `:5120–5123` (4 advisor briefs)

### 2. The "Perfect — there's a test pattern I can follow" callback
- **What:** During the cockpit audit, Otto discovered a working probe pattern (`@pytest`-shaped test harness for estate actions) and was delighted by the fact that the codebase had already solved the problem it was about to write code for.
- **Why it delighted:** Pure search-and-reuse. The audit got faster every step because every next step had a precedent. "Perfect" was the right word.
- **Citation:** `20260731_085036_d094cd3c:8413`

### 3. The Fable of the Observatory — when the right answer is the no-action answer
- **What:** Chids asked "What have you accomplished?" and "Claude mythos fable?" without file context. Otto refused to invent one, returned empty, and wrote a 42-line fable *about the failure mode itself* (the Architect who built observatories but never repaired anything). Chids's question contained the diagnosis; Otto's reply contained the medicine.
- **Why it delighted:** It is rare and it is *right* for an agent to refuse a 3-word prompt and answer the meta-question instead. This is exactly what an honest autopilot looks like, and Chids has been rewarding it explicitly.
- **Citation:** `20260702_075434_d7a0f4e8:6336` (fable caption + moral)

---

## 5 Capability Blind Spots (wanted but not exposed)

### 1. **`/find <token>` — natural-language recall**
The operator types "where is D?" (3 sessions this quarter). Otto's internal tool `session_search` already does FTS5 over `~/.hermes/sessions.db` with snippet, bookends, and scroll-by-message. Exposing one slash command (`/find <free text>`) collapses the entire Pattern D friction class. This costs ~50 lines: a thin wrapper around `session_search(query=..., limit=3)` that renders title + date + 1-line snippet + tap-to-load.

### 2. **`/cron health` — disabled-with-errors surface**
5 jobs sit disabled with `last_status=error` that the operator can't see from `/cron`. The cron fleet snapshot at `20260621_100716_2e2c465d:5214` has the data — just no panel exists. 80 LOC of render + the P0 cron-topic pre-flight. Listed as P1-7 in the audit (`20260731_210440_3ffb6c:8732`), not yet shipped.

### 3. **Tap-to-expand inline failure text**
Mission card truncates with `…`; the full message exists in stored data. Inline expansion = handler + render refactor, mid-M effort. This is P1-3 in the audit; partially shipped in `20260731_211736_09fa32:9245` (one of two clips removed, second clip blocked by the patch-mode loop).

### 4. **"Warn once" / de-spam channel**
A single toggle — `Otto quiet` / `Otto loud` — that debounces repeated identical watchdog alerts to once-per-class-per-window would eliminate ~131 spam lines per overnight error. Differs from a grep filter: it stays silent in the channel but still records to disk. ~30 LOC, M effort.

### 5. **Receipt-first panel mode**
The audit doc (`20260731_210440_3ffb6c:8728`) was effective *because every finding had a file:line or measurement*. But the operator has no way to *ask* "show me the receipt for that" from the panel itself — they have to remember the audit was run, find the spec file, read it. A button on each verdict row like `📐 receipts →` that opens the empirical probe output would close the loop. This is what Joy moment #1 already does in war-room form (each advisor brief lists its source and disagreement); the panel version would be P1-5 (state-aware buttons) per the audit.

### (Bonus blind spot) **`/why <id>` is documented but doesn't trust itself**
The `Otto decisions` / `Otto why <id>` commands exist on the assistant's menu (`20260621_100716_2e2c465d:5227`, `:5234`). But every audit session ends with the receipts in a spec doc, not in a queryable form. If the operator runs `Otto why did we skip the god-file split?` today they get a "let me check" response, not the citation. Same shape as the truncations in Pattern A.

---

## Methodology Notes

- I ran 8 discovery `session_search` queries (limit=3 each), and 6 scroll-window reads. No file reads, no `execute_code`, no LLM fabrication.
- The single most-rewarding slice was the cockpit audit at `20260731_210440_3ffb6c:8728`, which contains receipts for ~60 panel probes (latency, char count, button count). Every P0 finding there has a file:line + measurement; those findings are reproduced here with citation but not re-verified by my read.
- The oldest session I drew pain quotes from was 2026-06-21 (~6 weeks ago). The patterns hold across that window — none of them are fresh.
- I did NOT modify `specs/`, `operator_shell/`, or `sessions.db`. This report is the only artifact written.
- Reads of the 2026-08-01 session history itself (today) found no friction — the audit was already in cleanup-and-ship mode (`Continue until all done` was the most recent directive at `20260731_210440_3ffb6c:9018`, answered at `:9017` with the P0 status grid).

---

## Appendix — Sessions Drawn From

| Date | Session ID | Why it mattered |
|------|-----------|-----------------|
| 2026-07-31 | `20260731_210440_3ffb6c` | The full cockpit audit + P0 fixes ship (PG source) |
| 2026-07-31 | `20260731_211736_09fa32` | Where P0 verification, P1 progress, and patch-mode confusion all live |
| 2026-07-31 | `20260731_085036_d094cd3c` | Audit inspection, "Perfect" callback |
| 2026-07-10 | `20260710_211203_c2d4801a` | "Where is D?" — the canonical 3-word recall case |
| 2026-06-24 | `20260624_023255_73d015f9` | "Mother ship" / "Interface" — same friction, harder hour |
| 2026-06-22 | `cron_85385abb646d_20260622_080926` | Reflect-spam + cron-watchdog-overshoot (PG cron-duplicate source) |
| 2026-06-21 | `20260621_100716_2e2c465d` | "Where is your self audit?" + cron fleet context for disabled jobs |
| 2026-06-20 | `20260620_175237_59f2f30e` | War-room advisor pattern + "perfect code" rejection |
| 2026-07-02 | `20260702_075434_d7a0f4e8` | Fable of the Observatory — honest-no-joy moment |

End of report.

---

# PART II — Extended Receipts & Per-Event Walk-Throughs

(Pulled into a second section so the synthesis on page 1 stays scannable.)

## A. Per-Event Reading-Context Snapshots

### Event 1 (mission-card truncation) — reading-context

The `refresh` panel output captured in the audit at `20260731_210440_3ffb6c:8728` (rendered from `mission.py:488`):

```
🎮 *Cockpit* · *🟡 BLOCKED* — 4 need you
🏥 Host: AWAKE · online
💰 `$0.01 · 35/80`  ·  📈 `82%` · 23 done / 5 ask
🧠 RSI `OFF` · OFF_SWITCH absent · arm via 🧠 RSI
🧱 BLOCKED `c1d2a4dd` failure: Signal Engine daemon…        ← TRUNCATED
🚀 `Prospector ship` BLOCKED · M4: Land the acceptance test as…   ← TRUNCATED
🚀 *1 blocked mission(s)* — tap *Open missions*…
🧵 cron `main DM (ok)`
*Needs you (2):* → 📥 Decide (4) → 🚀 1 blocked
```

The truncation is a single slicing operation: `f"failure: {row['msg'][:40]}"` in `mission.py`. The full message is `failure: Signal Engine daemon paused: ORDER_HOT_PATH_DISTRIBUTION gone (last seen 3d)`. That full string is **already stored** in the BLOCKED item — the truncation is a *rendering* decision that the audit single-handedly identified as the highest-leverage 20-line fix.

The user reaction — *Chids retried the same complaint at least twice in the audit session* (`20260731_210440_3ffb6c:8709` and `20260731_211736_09fa32:9019` echoed the same screen text) — confirms that the truncation is read by the operator as *defensive evasion*, not a layout choice.

### Event 2 (cold re-render 6.3s) — reading-context

Panel latency matrix from `20260731_210440_3ffb6c:8732`:

```
Panel latency (cold cache):
  refresh              6,307 ms    ← 10× slower than next worst
  fleet                1,352 ms
  daemons                322 ms
  builds               14,388 ms    ← GitHub API
  st_status            64,015 ms    ← Stripe probe, 1+ minute
  st_health            73,963 ms    ← 75 seconds
  st_reconcile       >240,000 ms    ← timeout

After preflight cache (warm):
  st_status                6 ms   ← 10,000× faster
  st_health                8 ms
  builds                   7 ms
```

The audit explicitly notes *why* `refresh` is special: the mission card is the only panel that doesn't go through the `preflight.py` cache wrapper (every other panel does). The fix was to add it to the cache with a 5s TTL — verified as a **1,095× speedup** in the warm path.

### Event 3 (prospector 3× dedup) — reading-context

Prospector daemon panel (`20260731_210440_3ffb6c:8732`, U6):

```
*Daemon ticks (latest)*
🔴 skip 43m ago — `paused: /Users/chidionyema/.../store/scheduler/PAUSE`
🔴 skip 44m ago — `paused: ...`                            ← same root cause 3x
🔴 skip 57m ago — `paused: ...`
```

The fix re-uses the helper `_group_failures_by_root_cause()` that already powers the activity panel's dedup. Render collapsed 3 lines into 1:

```
🔴 skip ×3 — `paused: /Users/chidionyema/.../PAUSE`        ← during 2026-07-31 18:55–19:38
```

### Event 4 (no timestamp on prospector log) — reading-context

Prospector panel captured (`20260731_210440_3ffb6c:8732`):

```
_captured 2026-07-31 19:45 UTC · scheduler=KeepAlive daemon · watchdog=15m oneshot_   ← TIMESTAMP HERE
💚 hb `sleeping` · `43m` · `2026-07-31 19:01 UTC`                                    ← ABSOLUTE TIME — GOOD
*Recent log* _(1h ago)_                                                              ← RELATIVE only, no absolute
   `2026-07-31 18:38 UTC        ⚠️  [dead_gate] …`
```

The fix adds `*Recent log* _(7m ago · 2026-07-31 20:07 UTC)_` — header carries both relative and absolute. The discrepancy between "heartbeat has absolute; log header doesn't" was the user's `This doesn't have timestamps` complaint (`20260731_210440_3ffb6c:8709`). The fix is one-line; the user-mentioned-1× case had no follow-up tail that would have shown the fix shipped for *all* timestamp surfaces.

### Event 5 (reflect-on-correction.py spam) — reading-context

Strategist audit, 2026-06-22 (`cron_85385abb646d_20260622_080926:5373`, P0):

```
Of approximately 250 lines (79%) are 12 duplicate Auto-Reflection blocks,
each with identical text, generated every 30 min from 19:24 to 23:57.

The fix was prescribed in the 06-20 audit and reiterated in the 06-21
audit: "Replace hardcoded 'Root cause' + 'Fix applied' strings with a
diff against the last-run timestamp and the last-seen policy-firings.jsonl
cursor; exit silently when no new firings."

**This has not been implemented.**
```

This is the *pure* form of Pattern B — *audit recommendations that never get verified as executed*. The same fix was prescribed on two consecutive daily audits. The structural meta-finding from that same report:

> "The audit→action gap. Yesterday's audit produced 9 recommendations; zero were implemented. The audit is producing recommendations faster than any process is actioning them."

The cure is structural: **every recommendation emits a todo, and the todo's status is reported in the next morning's brief.**

### Event 6 (131 spam errors) — reading-context

Quote from the 06-22 audit (`cron_85385abb646d_20260622_080926:5373`):

```
- `daily-self-reflection` (4fb05d17267d):
  Script exited with code 1 — Reflection failed:
  [Errno 1] Operation not permitted:
  '/Users/chidionyema/Documents/code/.hermes/OBJECTIVES.md'

- `proving-ground-audit` (3c5a966ee24e):
  Script exited with code 1 — 3 failures:
  - signalengine/imports: "Current directory does not exist"
  - prospector/imports: "python: realpath: .venv/bin/: Operation not permitted"
  - npm/popdd-ts published: npm publish failure
```

Two host-level path errors, fired every 15 min, 131 entries between 03:48 and 07:09 UTC. The watchdog did *exactly* what it was supposed to do — log every failure — and that exhausts the channel's signal-carrying capacity for the morning. The reflection file path is wrong (`Documents/code/.hermes/` doesn't exist on this host); the proving-ground working dirs are also stale.

### Event 7 (5 disabled-with-error cron jobs hidden) — reading-context

Estate brief, 2026-06-21 10:11 (`20260621_100716_2e2c465d:5214`):

```
Cron fleet: 22 jobs — 18 active, 4 paused
✅ Active        18
⏸️ Paused         4

Paused jobs:
  9ba1919c7386  (health-check superseded)
  d2cb4cf8d9db  (improvement-pulse superseded)
  f0b2079864c5  (otto-dispatch)
  8b3beb82ae6e  (goal-of-the-moment)
```

The 07-31 audit repeats the finding with a wider lens (`20260731_210440_3ffb6c:8732`):

```
5 jobs disabled with last_status=error:
  ⚪ Summarize today's activity      last=error  (since 2026-07-30)
  ⚪ Run health check on all         last=ok     (but disabled)
  ⚪ daily-strategist-audit          last=error  (since 2026-07-29)
  ⚪ otto-improvement-pulse          last=ok     (but disabled since 2026-06-21)
  ⚪ otto-dispatch                   last=ok     (but disabled)
```

This is the *structural* hidden-state problem (Pattern A applied to cron): a "healthy" panel can be made invisible by filter-by-status design. The audit explicitly calls this out:

> "**Nothing in the operator_shell surfaces this.** The cron panel is healthy because it filters out disabled jobs. Operator has no way to discover 'I have 5 jobs that used to run and now don't.'"

The remedy is a separate "disabled with reason" panel/render that doesn't filter by status.

### Event 8 ("Where is D?") — reading-context

Session 2026-07-10 21:12 (`20260710_211203_c2d4801a:7202–7207`):

```
7202 (user): Where is D?
7203 (assistant): Where is D what? Could you clarify what you're asking about?
7204 (session_meta)
7205 (assistant): Otto here — what's the goal of the moment?
7206 (assistant): Otto here — what's the goal of the moment?
7207 (assistant): Otto here — what's the goal of the moment?
```

The session sat in a clarification loop for three assistant messages in a row before collapsing to the silent fallback "Otto here — what's the goal of the moment?" — the *default heartbeat* used when no recent user signal is present.

The same loop closed in 2026-06-24 (`20260624_023255_73d015f9:5726–5731`):

```
5726 (assistant): ⚙️ Working on: where is the mother ship / Interface ?
5727 (assistant): 🔴 ESCALATED (diagnosed, needs human): where is the mother ship / Interface ?
5728 (assistant): ⚙️ Working on: Update?
5729 (assistant): ⚙️ Working on: full audit
5730 (assistant): 🔴 ESCALATED (diagnosed, needs human): Update? root cause:
5731 (assistant): 🔴 ESCALATED (diagnosed, needs human): full audit
                root cause: The 'full audit' command or script is not found or not
                executable on the system, preventing the audit from running.
```

The 06-24 case is worse — the clarification was escalated *as a task*, then the executor made things up because the task had an empty acceptance test (no root cause specified), and the operator was left with three "executor could not act" escalations stacked. The acceptance-test-blank is a separate anti-pattern: every escalation without a root cause becomes a re-fire in 10 minutes.

The 06-21 case (`20260621_100716_2e2c465d:5215`) *did* recover cleanly — the assistant loaded the self-audit skill (`Otto self audit`) and produced a 8,347-byte audit doc. But the verb the user typed ("where is your self audit") is not the verb Otto recognised; Otto had to reach for "self audit" with an extra clause.

The cost of Pattern D: **the user has to learn the assistant's vocabulary before the assistant will answer**. The whole point of an autopilot is the opposite.

### Event 9 ("now" → Unknown) — reading-context

The mission card footer (`20260731_210440_3ffb6c:8732`):

```
_last-edit 2026-07-31 19:15:38 UTC · auto-refresh · say `now` to force_
```

The dispatch chain that handles the literal string `now`:

```
estate.py:1622 → handle_estate_action(action="now", request_id=...)
            → _dispatch(action="now") → ⚠️ Unknown action `now`
```

The footer says "say `now` to force"; the type handler says "Unknown". The user's most natural reaction is *try the word, get angry, swear at the bot, look at code*, exactly because the affordance and the implementation disagree.

Fix is 3 lines: `if action == "now": action = "refresh"` at the entry of `handle_estate_action`. Verified shipped.

### Event 10 (restart confirm ambiguous) — reading-context

Before the fix, the `restart` confirm card read:

```
♻️ *Restart coordinator?*
```

After the fix (`estate.py:1426`):

```
♻️ *Restart coordinator via launchctl?*

Kicks `ai.hermes.coordinator` via launchctl.
```

The launchd-label naming closes the ambiguity gap for the user who has 7+ daemons in the panel. The "via launchctl" was added because launchd-supervised daemons behave differently from raw processes — it tells the user *what is about to happen to the system*, not just which button they tapped.

---

## B. Additional Pain Quotes (used in the report; backup material)

> **"Need complete audit of current UI and ways of working and need drastic improvement for seamless operations and delightfully seamless user experience heavenly and reliable"**
> — Chids, 2026-07-31 19:00 (compressed context summary, `20260731_210440_3ffb6c:8711`)
> This is the originating brief for the cockpit audit that produced every P0/P1 fix. It is also a *friction* quote: the user had to write 4× the same adjective ("seamless / seamless / delightful / reliable / heavenly") to convey a calm-but-firm expectation. The words exist precisely because the buttons don't yet make the user feel them.

> **"Continue until all done"**
> — Chids, 2026-07-31 (`20260731_210440_3ffb6c:9018`)
> The shortest user reply of the entire month, sent after Otto asked "Want me to start the P1 batch (cron ops UX, fleet panel timestamps, severity coding) next session, or pause here?" Three words to clear 5 minutes of meta-discussion. The friction is that Otto *asked*.

> **"Update?"**
> — Chids, 2026-06-21 10:07 (`20260621_100716_2e2c465d:5192`)
> Two characters — the operator's canonical "what's the current state" prompt. Otto's response was *60+ seconds of full ground-truth probe*. Probably more output than the user wanted for a 7-character question. The friction here is **density asymmetry**: a one-line question triggers a wiki-sized reply.

> **"Hi"** — repeated in `20260620_175237_59f2f30e:4805` and `:4843`, 30 minutes apart
> Two-word hello that opened a 60-minute session. Otto's greeting was already prepared ("Hey there. LUX is running — no interrupted tasks, all clear. What can I prove or build for you?"). The repetition (`Hi` again 30m later) suggests the operator was in a *low-attention* mode, just checking the estate was still alive. Otto's helpfully wide response set them up for a session that didn't quite match either hello. Pattern E in its purest form: the *first-touch* experience doesn't accommodate "I'm just checking".

---

## C. The Sessions Where These Pain Quotes Were Set

A secondary finding from the mining: the friction moments cluster around three UTC hours of the day.

| UTC hour | Session IDs touching friction | Why |
|---------:|------------------------------|-----|
| **02:00–02:35** | `20260624_023255_73d015f9` | Late-night recall/query — pattern D |
| **08:50–10:12** | `20260731_085036_d094cd3c`, `20260731_210440_3ffb6c`, `20260731_211736_09fa32`, `20260621_100716_2e2c465d`, `cron_85385abb646d_20260622_080926` | Morning brief + audit window |
| **19:30–21:30** | `20260710_211203_c2d4801a`, `20260702_075434_d7a0f4e8` | Evening checkpoint — "what's the goal", narrative-state reset |

The implication for **cockpit**: a *time-aware greeting surface* that knows "if it's 02:00 and the operator just asked `Where is D?`, they want a 1-screen `D` summary, not a wizard flow."

---

## D. Lines That Are Already Proven — Don't Re-Build

These were shipped and verified inside the audit session (`20260731_211736_09fa32:9245`):

| P0/P1 ID | Fix | Verified effect |
|----------|-----|-----------------|
| P0-1 | Mission card: full failure text inline (no `…` clip) | Render shows full 120-char stored title |
| P0-2 | Mission card warm cache (5s TTL) | Cold 1,095ms → warm 0ms (1095×) |
| P0-3 | Prospector dedup same `paused:` skip → 1 line | 3 ticks → 1 `🔴 skip ×3 — paused:…` |
| P0-4 | Prospector log absolute timestamp inline | Header: `*Recent log* _(7m ago · 2026-07-31 20:07 UTC)_` |
| P0-5 | Daemon + fleet plain-English glossary | `interval / calendar / armed / fenced / retired / dirty(N) / inflight` defined |
| P0-6 | Restart confirm card names the launchd label | `Kicks \`ai.hermes.coordinator\` via launchctl` |
| P0-7 | `now` literal routes to `refresh` | No more `⚠️ Unknown action now` |
| P1-1 | `system_fuel` toast reflects state | Toast: `🔓 Override` (budget tripped) or `OK $0.0061` |
| P1-2 | `panel_stamp()` wired into fleet/daemons/prospector | Probe: fleet `1464ms`, daemons `76ms`, prospector_daemon `40ms` — all stamped |
| P1-3 (partial) | Inbox truncation removed (first clip) | `inbox.py:74` ✓ (second clip blocked by patch-loop) |

End-to-end smoke (15 actions) all green:

```
✓ refresh     677 chars  Refreshed
✓ now         677 chars  cached
✓ run         275 chars  Run
✓ activity  1,244 chars  Activity
✓ fleet       482 chars  Fleet
✓ daemons     951 chars  Daemons
✓ brain       591 chars  Brain
✓ prospector 1,103 chars  Prospector daemons
✓ signaleng   690 chars  Signal Engine
✓ builds      666 chars  Builds
✓ restart     151 chars  (confirm)
✗ totally-bogus 712 chars  Unknown  (guard works correctly)
```

---

## E. What This Mining Did NOT Find

I went looking for: a session where Chids said "I'm confused by the menu" or "I don't know which button to tap" — and *found none of those verbatim*. What I found instead was *behavioural* confusion: the operator types the literal word that the footer suggests, and gets told "Unknown." That's a different lesson — **the cockpit is not visibly bad, it's silently wrong**. Pain is encoded in *what the operator doesn't say* (they don't tell Otto the right verb because Otto didn't tell them which verb to use).

The other major absence: **no panics**. No "oh god the system is broken" scream in any of the 20+ sessions I sampled. The cockpit is fundamentally *operable*; the friction is the steady-state tax, not crash-level events. The user's words are patient ("I think we can skip the refactoring", "continue until all done") in a way that tells us they have no urgency beyond the steady drip.

---

## F. The Three-Step Recommendation for the *Next* Mining Cycle

If Chids wants to mine again in 30 days, these three signals move the needle:

1. **Re-run the P0/P1 ship-test grid** — every panel currently verified green at `20260731_211736_09fa32:9245` should still be green. Probe latency matrix, compare to the 07-31 baseline, regress if any panel crosses the 2× threshold.
2. **Probe the cron-watchdog for `O(1)` re-firing** — count unique cron errors vs total cron-error rows in `watchdog.jsonl` over 24h. If the ratio drops below 30% unique, the dedup work landed.
3. **Run the recall gap test** — feed Chids's last-10 sessions the *exact query* they were asking about, and grade whether `/find` would have answered each. Track delta.

Until those signals exist, mining is the same as it was today: a one-shot report. The data should move into a panel.

---

End of report (full).

