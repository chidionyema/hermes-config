# ESTATE_STATE — the single source of truth

**State is a probe, not a paragraph.** This file defines *what done means*. The live answer to
*"is it done?"* comes from running the probe — never from prose, memory, or any other doc:

```bash
bash ~/.hermes/scripts/verify_estate.sh      # prints R1–R5 + DEPLOY + DOOR + FENCES, PASS/FAIL
```

Exit 0 = OPERATIONAL. Exit 1 = DEGRADED. Every session (every agent) opens on this probe's output.
If a claim of "done" isn't backed by a green line in that output, it isn't done.

---

## What we are building (one paragraph)

A founder who runs his whole estate **from his phone**. One Telegram door — the **Hermes
gateway** (`ai.hermes.gateway`, long-polling the bot token). Through it he can: operate his
3 core projects (prospector, signalengine, tie), manage daemons, receive reports, run Otto
(operator_shell: panel / inbox / fleet / brief / missions), and **trust that every "done"
carries machine-verified proof** (acceptance tests + on-disk artifacts, not narrative).

Money (signalengine) and identity (tie) work is fenced: visible and triggerable only behind
approval, never executed unproven.

## The Mothership (one door — no second system)

**Door = Hermes gateway Telegram long-poll.** Exactly one process owns the bot token.

Retired (do not revive without an explicit dual-door decision):
- Cockpit uvicorn on `:8801` (`ai.hermes.cockpit`) — Disabled
- ngrok tunnel → `:8801` (`ai.hermes.ngrok`) — must be unloaded
- Telegram webhook → ngrok — must be empty (`getWebhookInfo.url == ""`)

Supporting daemons: `ai.hermes.coordinator` (task propulsion + heartbeats),
`ai.hermes.otto-server` (optional HTTP skills), `ai.hermes.watchdog` / estate_watchdog
(outer ring restart). Mission-card liveness uses **launchctl labels + `gateway.pid` /
`gateway.heartbeat` / `last_tick`**, never fragile `pgrep "gateway run"`.

## Acceptance — R1–R5 (what "satisfied" means, and the check that proves it)

| # | Requirement | Satisfied when | Probe check |
|---|---|---|---|
| R1 | Operate 3 core projects from phone | prospector + signalengine + tie in portfolio | `projects.json` lists all three |
| R2 | Manage estate from phone | operator_shell + otto-inbound route panels | code paths present |
| R3 | Reports on the phone | audit/daily reports deliver to Telegram | otto-inbound glob import |
| R4 | Run Otto | coordinator LaunchAgent + fresh `last_tick` + morning brief armed | launchctl + meta + cron |
| R4b | Otto can **act**, not merely run | gate armed in the live pid; `claude` reachable on the daemon's own PATH; both plists arm it; a non-fallback close within 48h | EXECUTOR |
| R5 | Proof, not theater | POPDD gate live on prospector | pre-commit hook + receipt |
| — | DEPLOY | gateway PID alive; hermes-agent tree known | `gateway.pid` + git status |
| — | DOOR | single Telegram door = gateway long-poll | launchctl + heartbeat + webhook empty + ngrok off |
| — | FENCES | money/identity never auto-execute | coordinator `awaiting_approval` |

**Why R4b is separate from R4 (2026-08-06).** R4 stayed green for two days while Otto's
tool-capable executor was 100% dead: the installed plist had drifted to bypass
`coordinator-daemon.sh`, dropping `COORD_AGENTIC_EXEC=1` and the wrapper's PATH, so every
executor spawn raised `FileNotFoundError` and fell through to chat narration. A running process
with a fresh tick is **presence**; R4b asks for **capability**. Every close between 2026-08-02
and 2026-08-06 18:55 carried a fallback marker — last real work 6.5 days earlier — and no probe
was red. Replayed against that clock, EXECUTOR prints
`❌ no real work in 6.5d and nothing closing — executor stalled`.

## The discipline (why this file exists)

The failure mode that nearly burned us: **status asserted in prose drifts from reality.**
A probe is authoritative; this doc is its index; all other estate narrative is reference/history.

- Single source of truth = the probe output. This doc = its map.
- "Written ≠ committed ≠ running" — DEPLOY + DOOR reconcile process identity with Telegram health.
- Product `done` requires `~/.hermes/reports/project-next-<key>.md` on disk (artifact gate).
- Older narrative that still says "cockpit + ngrok is the door" is **history** — the probe wins.

## Fenced (Claude-only / founder approval — never auto-run)

task:approve write · signalengine(money) / tie(identity) execution · RSI `OFF_SWITCH` arming ·
any unscoped `gateway/**` rewrite · D-155 money-smoke (£720+/run). These require explicit
founder authorization and a green proof gate first.

## Host sleep is not a cron outage (2026-08-13)

A host sleep longer than `WAKE_GRACE_S` produces **exactly one legitimate catch-up burst** on
wake, and `CRON_SILENT_STRETCH` / `CRON_STALE` are **suppressed across it** — that is designed
behaviour, not a missed alert.

- Incident: `pmset -g log` shows `2026-08-11 09:06:04 +0100 Entering Sleep state due to 'Low
  Power Sleep' ... Using Batt (Charge:0%)` → `2026-08-13 07:11:40 +0100 Wake from Standby ...
  EC.ACAttach`. ~46h asleep; the gateway process never died. On wake every `catch_up:true` job
  re-fired at `07:12:xx`. `scripts/watchdog.py` paged at `07:11:58` — 37s BEFORE the catch-up
  run — because the detector derived drift purely from wall-clock `now - last_run_at`.
- Fix: `scripts/watchdog.py` `_wake_grace()` (`WAKE_CATCHUP_GAP_S=1800`, `WAKE_GRACE_S=1200`,
  env-overridable). The watchdog's OWN inter-run gap is the sleep evidence; it is corroborated
  against `sysctl -n kern.boottime` (no reboot) and the gateway pid+start time (no crash/
  restart) before grace is granted, so a crashed scheduler still pages. Precedent:
  `scripts/estate_watchdog.py:45`, added after the identical 2026-06-21 false gateway-WEDGED page.
- Suppression is auditable: a `{"event":"wake_grace","gap_s":...}` line is written to
  `logs/alerts/watchdog.jsonl` on every suppressed tick.
- Proof: `/usr/local/bin/python3 ~/.hermes/scripts/test_watchdog_wake_grace.py` (exit 0).
- Jobs that lacked `catch_up` dropped their runs across the sleep. Set `catch_up: true` with a
  bounded `catch_up_window_s` (4h briefings / 1h pulses, per `hermes-agent/cron/jobs.py:1179`)
  on: otto-daily-digest, "Summarize today's activity", morning-briefing,
  reflection-digest-midday, reflection-digest-prebrief, reflection-pulse-30m, idle-curiosity,
  idle-continuous-learning, runaway-reaper.
- **Power settings are deliberately untouched.** The machine slept at 0% battery on Low Power
  Sleep; no software fence prevents that, and `install_keepawake.sh:5` explicitly declines to
  change `pmset`. Do not "fix" this with `ai.hermes.keepawake`.

## The estate probe runs itself now (2026-08-19)

`scripts/verify_estate.sh` is the live answer to "is the estate working?". Until today nothing
ran it on a schedule. No plist referenced it, so it only ever spoke when a human typed it, and
between two typings the estate could degrade for days without saying so. Three daemons running
stale code and a stopped CI machine were all found by hand, not reported.

It now runs inside `scripts/hermes_selfcheck.py`, which launchd already runs hourly:

```
~/Library/LaunchAgents/ai.hermes.selfcheck.plist   StartInterval 3600, args: --alert
launchctl print gui/$(id -u)/ai.hermes.selfcheck   # runs, last exit code, interval
```

**What reaches Telegram, and what does not.** `_alert_on_change` compares the SET OF FAILING
CHECK NAMES against `state/selfcheck.json`. A new failure pages once with its detail and the
command that reproduces it. A failure that clears pages once. An unchanged failure set is
silence — repeating an unfixed fault every hour trains you to ignore the channel, which is how
the one new fault arrives in a stream nobody reads.

**One row per fault, never one lump.** Because alerting keys on names, a single composite row
called "estate probe" would page on the first fault and then stay silent however much worse
the estate got: the set would never change again. Every `❌` line the probe prints becomes its
own result row. The `VERDICT:` line does not — it summarises the rows above it and would
appear and clear in lockstep with them.

**The name is masked, the detail is not.** The probe prints a pid and an elapsed-hours figure
that move every run. Unmasked, an unchanged estate would look like a brand new failure set
every hour. Both are replaced in the NAME only (`pid N`, `Nh`); the raw line is kept as the
detail an operator reads. Nothing else is masked — an exit code going from 78 to 2 is news.

**Cannot-establish is a FAIL.** A probe that hangs past 180s, or cannot be run at all, or exits
non-zero while marking nothing, registers a failure. A measuring instrument that reports "all
clear" when it is the broken thing is the defect this whole file exists to refuse.

**Alerts are capped at Telegram's ceiling.** Telegram rejects a message over 4096 characters
outright — the whole message, not the tail — so the alert with the most to say was the one most
likely to arrive as nothing. `estate_alert._fit` trims on a line boundary and says how many
lines it dropped. Measured 2026-08-19: 11 estate faults build 2767 characters.

Pinned by `tests/test_selfcheck_estate_probe.py` (8 cases, 6/6 mutants killed) and
`tests/test_estate_alert_fits_telegram.py` (5 cases, 3/3 mutants killed), including one case
that proves the cap is actually CALLED by the sender rather than merely existing.

## Telegram noise is a measurement now, and it has a ceiling (2026-08-19)

Founder, 2026-08-19: the channel is "too noisy, hard to see anything useful".

Both alert paths already debounced. `estate_alert._debounced` holds a repeat of the same
key for 300s; `estate_watchdog._alert` holds one for 1800s. Neither was the problem, and
neither could have shown it, because **nothing recorded what had been sent**. There was no
number to argue with — only an impression.

### The ledger

`scripts/telegram_ledger.py` appends one row per attempted send to
`~/.hermes/state/telegram_sent.jsonl`: time, sender, outcome, length, opening line, debounce
key. Two decisions in it are load-bearing.

It records **suppressed** sends, not just successful ones. A debounce doing its job is
invisible, and an invisible mechanism gets deleted by the next person who reads the code and
concludes it does nothing.

It **bounds itself**. `_trim` keeps the newest 20,000 rows once the file passes 8 MB. Adding
an unbounded log to fix a storage problem is the joke version of this work.

An **edit is not a send**. The coordinator's progress stream edits one message per task
instead of posting a line per step. Counting edits as sends would rank the quietest design in
the estate as its loudest sender.

Wired: `estate_alert.send_operator_alert` (sent / suppressed / failed / no-creds /
rate-capped), `coordinator.telegram_notify` and `coordinator._hermes_send_capture` (sent /
edited / failed / muted).

### The report

```bash
python3 ~/.hermes/scripts/telegram_noise.py --since 24h
```

Read-only, sends nothing. Volume by sender, by outcome, by hour, and the most repeated
opening lines — because forty copies of one message is a different fault from forty different
messages, and the fix differs too.

### The ceiling

`HERMES_ALERT_HOURLY_CAP`, default 12. Per-alert debouncing cannot see the total: twenty
distinct faults, each correctly un-debounced, still bury the one message worth reading.

Past the ceiling, alerts stop reaching the channel and **one** line goes instead, naming the
count and the command above. One notice per hour, not one per held alert — a cap that
announces every suppression is louder than no cap, because the announcement never debounces.
Nothing is lost: every held alert is in the ledger in full. `0` turns the ceiling off.

### Tests

`tests/test_telegram_ledger_and_cap.py`, 16 tests, mutation-checked 9/9. The nine killed
mutants: announcing the cap on every held alert, not recording a held alert, counting all
history instead of the last hour, reading `0` as "allow zero alerts", an off-by-one at the
ceiling, recording a dry run as a send, trimming to the oldest rows instead of the newest,
letting a ledger write failure escape into the alert path, and counting an edit as a message
in the channel.
