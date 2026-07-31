# Operator Shell — Elon-caliber Telegram Cockpit

## One rule
Exactly one process owns the bot token: **Hermes gateway**. Cockpit LaunchAgent is Disabled.

## Chat router (single ordered pipeline)
Telegram CEO verbs have **one owner**: `plugins/otto-inbound` → `pre_gateway_dispatch` →
`gateway.operator_shell.chat_router.route_telegram_ceo`.

| Step | What | Outcome |
|------|------|---------|
| 1 | `natural_ops.match` → `handle_estate_action` | skip (panel) |
| 2 | `code_remote` assign / steer / task | skip (receipt) |
| 3 | noise (`ok`/`hi`) → mission card | skip |
| 4 | slash / surface leftovers (inbox, fleet…) | skip |
| 5 | CEO free chat: noise already card; substantive | **allow → agent** |

Gateway `_handle_message_with_agent` natural_ops is **fallback only** (voice STT after
plugin saw empty caption, or plugin missing). Same verb must not double-send.

## Mission card (`/panel` · `ok` · CEO default)
Pinned when send path succeeds:
- 🟢/🟡/🔴 verdict · **host AWAKE/at-risk** · burn · **product autonomy** · **RSI armed/idle+reason** · blocker · cron topic · CTA
- Never 🟢 CLEAR when paused / daemon|gateway down / budget / CB / inbox / blocked mission / inflight code
- Host line uses wake grace (15m) after Mac sleep so stale heartbeats don't false-ALARM

**Buttons:** Pause/Resume · Fleet · Daemons · Inbox · CI · RSI · Cron · Fuel

## Always-on host (Mac-local)
- LaunchAgent `ai.hermes.keepawake` → `caffeinate -ims` (idle + disk + AC system sleep; display may sleep)
- Install / repair: `bash ~/.hermes/scripts/install_keepawake.sh`
- Phone: `host` · `keep awake` · `estate online` → host panel · *Start keep-awake* / *Refresh*
- Away alarm (watchdog, debounced): keepawake down OR gateway heartbeat stale → Telegram DM
- **Still Mac physics:** lid close, battery, thermal, low-power can sleep despite caffeinate

Optional one-time (sudo — founder only):
```bash
# System Settings → Energy → Prevent automatic sleeping on power adapter (preferred)
# or:
sudo pmset -c sleep 0 disksleep 0
sudo pmset -c displaysleep 10
```

## CEO mode (default)
`operator_shell.mode: ceo` in `config.yaml`.
- Short noise (`ok` / `hi`) → mission card
- Substantive free chat → agent reply (not silent card)
- Work: `Otto, <task>` (tracked + proof receipt with `rid:`)
- Force agent: `Otto engineer: <question>`
- Switch: set `mode: engineer` or `OTTO_MODE=engineer`

## Daemons (phone)
- `daemons` — `ai.hermes.*` + TIE review if installed
  - KeepAlive (gateway/coord/keepawake/otto-http) → pid
  - Interval/calendar (watch/progress/rsi/tie) → 🟢 armed between ticks (not false 🔴)
  - Logs · run watch now · bounce gateway (confirm/fenced start)
- `prospector daemon` / `prospector params` / `prospector cron` — generation control
  - Safe knobs (confirm+proof): interval · concurrency · batch · daily_cap · PAUSE
- Phrases: `daemons` · `host` · `keep awake` · `restart gateway` · `restart coordinator` · `coord logs` ·
  `run hermes watchdog` · `prospector params|cron|logs` · `pause/resume prospector`

## Store money rail (phone) — `st_*`
Thin bridge (`gateway/operator_shell/store_ops.py`) onto
`~/Documents/code/prospector/store_platform/scripts/storeops --brief`. It shells out and formats;
it never re-implements a verdict, so the phone and the terminal can't disagree.
- `store` / `store status` — daemon state · store sellable · every buyer delivered
- `store health` · `can we take money` · `are we sellable` — full production probe
- `reconcile` · `buyers` · `paid without delivery` — Stripe paid vs what the store delivered
- `store money` — offline money-path proof
- 🟢 exit 0 · 🔴 exit 1 (checked and broken) · 🟡 exit 3 (**could not check** — never folded
  into green; that conflation is the failure this tool exists to catch)
- **Read-only.** No `deploy` verb: `fly deploy` ships the working tree, so it stays a terminal
  action. No `pause store` either — `store/scheduler/PAUSE` already answers to `pause prospector`,
  and one switch must not have two names.
- Runbook: `~/Documents/code/prospector/store_platform/OPERATIONS.md`

## Cron delivery (private DM honesty)
Home chat is a **private bot DM** (`getChat.type=private`). Telegram does **not** show a
Topics toggle on the bot profile — that UI is for groups/forums. Live proof:
`createForumTopic` → `chat is not a forum`.

**What works:**
1. Mission card → *🗓 Cron delivery* → *Keep cron in this chat* (`TELEGRAM_CRON_IN_MAIN_DM=1`)
2. Optional Topics: private group → enable Topics → add Otto → Cron topic → `/sethome`
   (sets `TELEGRAM_CRON_THREAD_ID`). Never invent a thread id.

## Inbox / Fleet / Brief
`/inbox` — approvals only · `/fleet` — four products · `/brief` — 5-line sitrep

## The spine: Now / Run / Tune / 🔎
Every screen ends with the same row. The split between the three is the whole architecture —
put a new control in the one that matches, and it lands where the operator already looks.

| | holds | test |
|---|---|---|
| ⚡️ **Now** | what is true, and the fix for what is broken | *a read, or a button that resolves a live concern* |
| 🎛 **Run** | the verbs — start, stop, restart, run now, bounce, pause | *it changes what is happening right now* |
| ⚙️ **Tune** | the 29 knobs — leverage, caps, batch size, cadence | *it changes configuration and survives a restart* |

**Now is generated from state.** `mission.py::_concerns()` walks the severity ladder and returns
**every** rung that fires, most severe first; each one prints a line and carries its own button,
capped at 3. `_primary_cta()` is now just `_concerns()[0]`. Before this the ladder was walked in
full, the first hit returned, the rest discarded, and a fixed nine-button menu stapled underneath
regardless of what was wrong — the cockpit knew about the money fence *and* the dead coordinator
*and* the blocked missions, and showed you one of them plus a menu.

**Search is the fourth position, because three containers were not enough.** The measured
shape after the regroup: 131 destinations across 76 panels. That is well past where browsing
works — *"buttons may exist but the ui is so confusing i dont know where to find anything"*
(founder, 2026-07-31). `find.py` answers a typed word with the buttons that match it: `find
restart`, `where is the spend cap`, `how do i switch model`, or 🔎 from any screen.

The index is **derived, never hand-written**. `natural_ops._PATTERNS` is already the list of
things this estate can do *and* the words an operator would use to ask — the regex literals are
the vocabulary. A hand-kept second list drifts on the first rename; this one gains a new op the
moment the op exists. Hits that need an argument (`approve <id>`) are printed as text rather
than offered as a button, because a button that cannot work is worse than no button.

**What those "type this" lines say is derived too — the first version was wrong.** Search
shipped printing the *internal action name* as the command: `se_set <id>`, `brain_set <id>`,
`code_assign <id>`. None of those are commands. Measured against the live router,
`match_natural_op` returned `None` for **6 of the 10** arg-taking ops — the feature built to
answer "I can't find anything" was naming destinations that do not exist. `usage.py` now walks
the parsed regex and emits the phrasing the pattern actually accepts (`use opus`,
`assign <text>`, `pause <id>`, `set signal exec_mode <value>`), taking the first alternative of
every branch and a concrete value wherever the regex enumerates them. Proof it stays true:
`test_find.py` types every derived hint back through `match_natural_op` and fails unless it
lands on its own action — the same round-trip, re-run on each pattern edit. Where derivation
fails the line reads "ask for it in plain words" rather than inventing a command.

**One destination, one row.** `find` is registered twice (argless panel, and `find <query>`),
so a search for "search" printed *Find anything* as a ⌨️ line **and** as a button — the
duplicate-button defect already fixed twice on the home card, back for a third time by a
different route. Entries sharing an action *and* a label now collapse to the tappable one.

**🧠 Brain lives under Tune.** The model is configuration in the same sense as a spend cap: it
persists, it costs money, and until now it was only reachable by typing `/model <name>` from
memory. Each choice pins its provider — verified against the live resolver, `opus` without an
explicit provider resolves through OpenRouter rather than the direct anthropic transport the
key is for. The panel promises *"your next message"*, not *"immediately"*: `run.py:16091` evicts
the cached agent on config drift after a run completes, and that is the real contract.

**Tune is grouped by consequence, not by daemon.** Sizing and Safety are separate because they
fail differently; Spend is one screen because a daily ceiling is a daily ceiling whichever daemon
is burning it. No **group** exceeds 9 buttons.

**Tune's index adapts; the groups do not.** Grouping killed the 28-button screen but left every
knob three taps away, which is exactly where it started. Two changes cut that without rebuilding
the wall of buttons:

- `render_tune()` promotes the last 2 knobs you actually *changed* (from the activity log,
  successful sets only — promoting a knob because it keeps erroring would be backwards) to the
  index with their values inline. Those go **3 taps → 2**. A knob you have touched is
  overwhelmingly the knob you touch again; most of the 29 are set once and never revisited.
- After a set, `estate.py::_knob_landing()` returns you to the knob's **Tune group**, not to the
  read-only `se_params`/`pd_params` panel. Changing a second knob in the same group goes
  **3 taps → 1**. Unknown key falls back to the read panel.

First touch of an un-promoted knob is still 3 taps. That is the honest number.

**No screen may offer the same callback twice.** Seven of 26 panels did, every one because a panel
added a button the spine already carried. `nav()` now drops its `🔄` when the self-action *is* a
spine action, so callers cannot get it wrong. Where a panel genuinely wants both, the live concern
wins and the static tile gives way — never dedupe blindly "keep first", which eats the spine.
Verified by sweeping all 76 reachable panels, not by reading code.

**Every tap is recorded.** `gateway/operator_shell/activity.py` appends one row per action to
`~/.hermes/meta/operator_shell/activity/<date>.jsonl` — action, arg, outcome parsed back out of
the `Proof` receipt, duration, error. It is hooked by making `handle_estate_action` a thin wrapper
over `_dispatch`, because `_dispatch` has dozens of return paths *and can raise*, and the raise is
the outcome most worth auditing. Read it at ⚡️ Now → 🎛 Run → 📜 Activity, or say "activity".
Recording never raises: an audit trail that can take the cockpit down is a liability.

```python
from gateway.operator_shell.panel_chrome import nav, clip
buttons = [ ...panel's own rows... , nav("my_action")]   # nav is ALWAYS the last row
```

- `nav(self_action)` → `⚡️ Now · 🎛 Run · ⚙️ Tune · 🔄`. The refresh is the bare glyph so four
  buttons fit one phone row. It re-renders **this** panel, so it means the same thing everywhere.
- **A live action never shares a row with nav.** `▶️ Run watch`, `📡 feed on`, `🟢 Arm` and
  `▶️ Start keep-awake` each used to sit inside a navigation row; a thumb aiming for "back"
  landed on them. They now get their own row.
- **Truncate with `clip()`, never `text[:60]`.** A raw slice cuts mid-word with no marker, so a
  clipped blocker reads as a finished sentence.
- **Do not print a field you cannot fill.** Fleet used to label the first line of a markdown
  file `blocker:`; it now prints nothing when the report names no blocker.
- **One place per knob.** `se_params` / `pd_params` show values and link to the Tune group that
  changes them. Two screens that both set leverage is how they drift.
- **A button that cannot act is worse than a missing one.** Run offers `▶️ Start` only when the
  thing is stopped. When a probe *fails*, it says `?` and offers both — never guesses.

### Why it changed (measured, not asserted)
BFS over the real button graph, expanding read-only panels only:

| | before | after |
|---|---|---|
| destinations at 3 taps | **45 of 83** | see `panel_chrome` docstring |
| `se_params` buttons on one screen | **28** | 4 group links |
| Signal Engine allowlisted values reachable | **23 of 29** | **29 of 29** |
| panels with no inbound button at all | `estate:host` (331 lines) | none |

`per_instrument` — an entire risk cap — had no button anywhere, and `stop_loss: 0` meant the
cockpit could tighten the stop and never release it. The densest screen in the cockpit was
*simultaneously* the most incomplete, which is what a wrong container looks like rather than
too many features. Callback parity: **90 → 107, lost 0.**

The same sweep run to depth 6 (76 panels, 131 destinations) found two panels that were simply
broken, neither of which any unit test covered:

- **👁 Inspect raised on every tap.** `estate.py` called `.get()` on a `sqlite3.Row`, which has no
  such method — and `decisions_view` / `backlog_view` do not even select the same columns, so
  subscripting would have `KeyError`d on half the matches. Both views are `dict()`ed now.
- **RSI offered `arm_learning` under two buttons when disarmed** — the suggested next action *was*
  arming, which the standing toggle already carried.

A whole-graph probe finds what tests do not, because `tests/conftest.py` redirects `HERMES_HOME`
to a tempdir and a full dispatch there returns the one-button error fallback. **Any probe that
taps live buttons needs a write denylist wider than it looks:** mine matched substrings and let
`disarm_learning` through, so it toggled the real `OFF_SWITCH` for two seconds mid-sweep.

## Autonomy compounding
| Switch | Meaning |
|--------|---------|
| `~/.hermes/meta/OFF_SWITCH` **present** | Learning **ARMED** |
| **absent** | **DISARMED** (RSI + meta-improver + idle-learning fail-closed) |

- Product autonomy metric excludes status-report / CRON / junk
- diagnose/execute inject policies via `memory_retrieval`
- Escalation drain: junk · healthy CRON · provider-quota parks
- Portfolio pull pauses while Claude circuit-breaker is open
- Corpus: 25 unique classes · ~52% honest coverage
- RSI stages only; Telegram Double-Key merge (`prompt:approve:*`)

## Cron / briefs
| Job | What |
|-----|------|
| `morning_brief.py` | 09:00 deterministic CEO brief (no LLM) |
| `weekly-progress-digest.py` | Sun 18:00 product autonomy · RSI · auto-closed · one ask |
| Relist / daily summarize | **Paused** (provider rot) |

**Cron:** tap 🗓 → *Keep cron in this chat* (private DM), or `/sethome` inside a Topics group Cron topic.

## P0 notify backup
Set in `~/.hermes/.env`:
```
NTFY_TOPIC=your-private-topic
OPERATOR_SHELL_ALWAYS_NTFY=1   # optional: always dual-path
```
Gateway patches coordinator notifier on boot.

## Tier-0 chat menu
`/panel` `/inbox` `/fleet` `/brief` `/cron` `/busy` `/notify` `/revert` `/missions` `/audit` `/help`

```bash
python3 ~/.hermes/scripts/set-cockpit-menu.py
launchctl kickstart -k "gui/$(id -u)/ai.hermes.gateway"
```

## Arm / disarm learning
```bash
python3 ~/.hermes/scripts/learning_switch.py arm    # or: Otto arm self-improvement
python3 ~/.hermes/scripts/learning_switch.py disarm
```


## Restarting the gateway from the gateway

The button was never missing (`estate:daemon_restart:gateway`). Its **answer** was.

PROVEN 2026-07-31 with a disposable launchd job: a process that runs `launchctl kickstart -k`
on its own label is SIGKILLed *inside* `subprocess.run`. The probe wrote a `BEFORE` line, then
never the `AFTER` on the next statement — twice, with two different pids. Everything after that
call in `daemons.run_op` (the receipt, the PanelView, the `activity.record` row) was unreachable
whenever the target was the gateway itself. The estate restarted; the phone showed nothing.

`daemons.restart_self()` hands the job to a detached child (`start_new_session=True`) that waits,
sends a graceful TERM, and kickstarts as a net. The panel returns first. `is_own_job()` decides
by **pid**, not by name — the same module is imported by the CLI, the tests and the gateway, and
only the process launchd reports for that label may take the deferred path.

Stopping ourselves is **refused**, not silently upgraded to a restart: `start` is fenced for the
gateway (`_FENCED_START`), so a stop from inside the gateway closes the only door back in.

## Staleness: why the gateway ran old code

Not packaging. `hermes_agent` is installed editable, so every start already imports
`~/.hermes/hermes-agent`. The gap was that nothing *caused* a start when the tree changed —
restarts happened for unrelated reasons (110 logged connects), so whether the running code
matched the tree was luck.

`gateway/source_watch.py` fingerprints the four runtime packages (count, newest mtime, total
bytes — stat-only, no hashing) every 15s and exits once the tree has been quiet for 20s.
launchd `KeepAlive` brings it back on the new code, through the same drain-and-resume path a
manual restart takes. Three guards, because a self-restarting process that gets one wrong is a
crash loop: only when supervised (`ppid == 1`), only after quiet, never twice. Off switch:
`HERMES_GATEWAY_AUTORELOAD=0`.

Proof it works, from the deploy that shipped it — the watcher restarted the gateway on its own,
before anyone asked:

```
19:19:31 WARNING gateway.source_watch: Source watch: gateway source changed and settled —
                 restarting so the new code is live (in-flight sessions drain and auto-resume)
19:24:55 INFO    gateway.source_watch: Source watch: active — 392 source files
```

**The reload had to declare itself planned, or the probe called the estate broken.** The
watcher restarts by SIGTERMing itself — and `run.py` classifies an *unmarked* SIGTERM as
unexpected and exits **1** so a service manager revives it. launchd records status 1, and the
LAUNCHD section of `verify_estate.sh` reads that back as `ai.hermes.gateway last exit=1 — job
is failing every run`, flipping the whole verdict to **DEGRADED**. Measured on 2026-07-31: a
green estate went DEGRADED purely because the watcher had done its job. That is the failure
that section was written to prevent — a permanent red trains the eye to ignore the real one.

`signal_planned_restart()` now writes the takeover marker naming its own pid before the
signal, which is exactly what `consume_takeover_marker_for_self()` matches, so the handler
exits **0**. Safe because this job is `KeepAlive => 1` (unconditional) — launchd revives it on
a zero exit just the same; a job with `SuccessfulExit=false` would have needed a different fix.
Proven live, both directions:

```
before   launchctl list -> 87934  1  ai.hermes.gateway   VERDICT: ❌ DEGRADED
after    launchctl list -> 90920  0  ai.hermes.gateway   VERDICT: ✅ OPERATIONAL
```

An unrelated SIGTERM still exits non-zero and stays visible — `test_source_watch.py` pins
both halves, including that a failed marker write costs a false red but never the restart.
