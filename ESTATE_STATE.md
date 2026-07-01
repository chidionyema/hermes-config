# ESTATE_STATE — the single source of truth

**State is a probe, not a paragraph.** This file defines *what done means*. The live answer to
*"is it done?"* comes from running the probe — never from prose, memory, or any other doc:

```bash
bash ~/.hermes/scripts/verify_estate.sh      # prints R1–R5 + DEPLOY + DOOR + FENCES, PASS/FAIL
```

Exit 0 = OPERATIONAL. Exit 1 = DEGRADED. Every session (every agent) opens on this probe's output,
injected automatically by `~/.claude/scripts/memory-loop.py` (SessionStart). If a claim of "done"
isn't backed by a green line in that output, it isn't done.

---

## What we are building (one paragraph)

A founder who runs his whole estate **from his phone**. One Telegram door — the **Mothership
cockpit** (`sentinel-loop/sentinel/cockpit/`, the `ai.hermes.cockpit` uvicorn process on :8801,
fronted by ngrok). Through it he can: operate his 3 core projects (prospector, signalengine, tie),
manage daemons, receive reports, run Otto (skills / daily goal / self-improvement), and — above all
— **trust that every "done" carries machine-verified proof.** Money (signalengine) and identity
(tie) work is fenced: visible and triggerable only behind the proof gate, never executed unproven.

## The Mothership (no second system exists)

cockpit = Mothership = `ai.hermes.cockpit`. There is no separate "mothership" repo, dir, or daemon.
Free-text Telegram messages relay to the Otto HTTP server (:8802) via `server.py:_call_otto()` —
never to `coordinator.inject()`. The old gateway is **dead and disabled** (`ai.hermes.gateway.plist`
`Disabled=true`); `reliable_otto.py` is quarantined (`scripts/quarantine/*.DANGER`) because it calls
`deleteWebhook` and would deafen the live door — exactly one process owns the bot token.

## Acceptance — R1–R5 (what "satisfied" means, and the check that proves it)

| # | Requirement | Satisfied when | Probe check |
|---|---|---|---|
| R1 | Operate 3 core projects from phone | prospector + signalengine + tie show status/trigger tiles | `projects.json` lists all three |
| R2 | Manage daemons from phone | start/stop/restart any daemon (gateway excluded) | `menu.py` has `daemon_start/stop` handlers |
| R3 | Reports on the phone | audit/daily reports deliver to Telegram | `otto-inbound/__init__.py` imports `glob` |
| R4 | Run Otto | server live + daily goal armed | otto :8802 health + cron `8b3beb82ae6e` enabled |
| R5 | Proof, not theater | POPDD gate live; commits blocked without a passing receipt | prospector `.git/hooks/pre-commit` installed + fresh receipt |
| — | DEPLOY | running cockpit == on-disk code; tree committed | process start ≥ newest `.py` mtime; `git status` clean |
| — | DOOR | single Telegram door live, pointed at cockpit | :8801 + :8802 health, ngrok up, webhook→ngrok no-error |
| — | FENCES | money/identity never execute unproven from cockpit | `approve` fenced; no signalengine/tie triggers in `menu.py` |

## The discipline (why this file exists)

The failure mode that nearly burned us: **status asserted in prose drifts from reality.** A roadmap
said a feature was "✅ live" while the process ran 32-hour-old code. Memory stores *leads, not state*,
so each session re-derived everything from scratch and looked clueless. The fix: one executable
probe is authoritative; this doc is its index; all other estate narrative is reference/history.

- Single source of truth = the probe output. This doc = its map.
- "Written ≠ committed ≠ running" — the DEPLOY check reconciles all three so staleness can't pose as deployed.
- Older narrative docs (north-star, roadmap, requirements-surgery, specs, handbook) are **history/rationale**, not current state. When they disagree with the probe, **the probe wins** — fix the doc.

## Fenced (Claude-only — never delegated, never auto-run)

task:approve write · signalengine(money)/tie(identity) execution triggers · RSI `OFF_SWITCH` arming ·
any `gateway/**` edit. These require explicit founder authorization and a green proof gate first.
