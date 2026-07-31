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

## The spine: Now / Run / Tune
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

**Tune is grouped by consequence, not by daemon.** Sizing and Safety are separate because they
fail differently; Spend is one screen because a daily ceiling is a daily ceiling whichever daemon
is burning it. No group exceeds 9 buttons.

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
