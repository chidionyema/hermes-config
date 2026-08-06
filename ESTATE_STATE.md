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
