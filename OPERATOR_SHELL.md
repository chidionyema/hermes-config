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
