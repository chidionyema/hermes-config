# Operator Shell — Elon-caliber Telegram Cockpit

## One rule
Exactly one process owns the bot token: **Hermes gateway**. Cockpit LaunchAgent is Disabled.

## Mission card (`/panel` · `ok` · CEO default)
Pinned when send path succeeds:
- 🟢/🟡/🔴 verdict · burn · **product autonomy** · **RSI armed/staged** · blocker · next cron · CTA

**Buttons:** Pause/Resume · Fleet · Daemons · Inbox · CI · RSI · Cron · Fuel

## CEO mode (default)
`operator_shell.mode: ceo` in `config.yaml`.
- Short noise (`ok` / `hi`) → mission card
- Substantive free chat → agent reply (not silent card)
- Work: `Otto, <task>` (tracked + proof receipt with `rid:`)
- Force agent: `Otto engineer: <question>`
- Switch: set `mode: engineer` or `OTTO_MODE=engineer`

## Daemons (phone)
- `daemons` — estate `ai.hermes.*` (gateway start fenced; Hermes watch ≠ Prospector watch)
- `prospector daemon` / `prospector params` / `prospector cron` — **full control card**
  - **scheduler** KeepAlive = real generation daemon; watchdog = 15m oneshot (🟢 armed when loaded)
  - Same panel: live params · hermes cron outcomes · daemon ticks/failures · logs
  - Safe knobs (confirm + proof; plist changes auto-restart scheduler): interval 1h/2h/4h · concurrency 2/4/8 · batch 3/5/10 · daily_cap $10/$20/$40 · PAUSE file
  - Phrases: `restart/start/stop prospector` · `run prospector watchdog` · `prospector logs` · `pause/resume prospector` · `set prospector batch_size 5`
  - Buttons: Restart/Stop/Start · Params · Cron · Logs · Run watch · Fleet

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
| Strategist / daily summarize | **Paused** (provider rot) |

**Cron topic:** tap 🗓 on `/panel` (enable Topics in the bot DM first), or `/sethome` inside a Cron topic → sets `TELEGRAM_CRON_THREAD_ID`.

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
