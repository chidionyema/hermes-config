# ESTATE NORTH STAR — operate everything from Telegram, prove every word

*War-room dissection 2026-06-25. Every claim below is backed by `file:line` or command
output. Anything not proven is marked HYPOTHESIS/UNPROVEN. This document is a guideline, not
a change — nothing here has been executed.*

---

## 1. THE INTENT (the bar we are building to)

> The CEO of Anthropic wants **total oversight** of this estate and to **operate all of it
> from Telegram and the mothership cockpit, flawlessly — and to never be told anything that
> isn't provably true.**

Three non-negotiables fall out of that:

1. **Total visibility** — every daemon, task, mission, cron job, satellite project, dollar of
   spend, and alert is *see-able* from Telegram / the cockpit.
2. **Total control** — every lever (approve, inject, pause, restart, stop, trigger, unblock)
   is *operable* from Telegram / the cockpit, behind the security fences.
3. **Zero hallucination to the operator** — anything the estate tells the operator is either
   ground-truth (read live from db/config/process) or a verified, signed claim. No bare LLM
   assertion reaches the operator unlabelled.

This file is the guideline that all convergence work serves. SOUL.md is *who* the estate is;
this is *what operating it must feel like*.

---

## 2. WHAT THIS ESTATE ACTUALLY IS (and why — do NOT naively retire any of it)

It is **not** redundant sprawl. It is a **layered defense system**: a bare `hermes-agent`
gave a Telegram gateway, a SQLite coordinator, and cron — but *no execution discipline*. Each
layer below was added **after a specific failure was observed in the running estate**. The
evidence for each "why" is cited.

| Layer | The failure it was built to kill | Proof |
|---|---|---|
| **Sentinel loop** | "Stuck Agent" — compounding broken edits in a loop; agent divergence | SPECIFICATION.md:5,92 |
| **Coordinator (single-writer)** | "done" theater + zero-delivery (25/37 tasks were internal plumbing) | SPECIFICATION.md:183; commit e73f7d6 |
| **Watchdog** | hung processes; three daemons silently dead | SPECIFICATION.md:79-80; ESTATE-V2:75 |
| **Fiscal Sentry** | runaway paid token spend (`token_budget=None` → never trips) | SHIP_READINESS_REVIEW.md:53 |
| **3-strike + worktree sandbox** | workspace contamination of the live source tree | SPECIFICATION.md:63,92-123 |
| **Cockpit / Mothership** | operator blindness — no remote DevOps surface | SPEC_COCKPIT.md:3-5 |
| **LUX (PDD)** | "it compiles / tests pass" treated as proof; only covers cases you thought of | lux-proof-driven-development/SKILL.md:1-16 |
| **POPDD (chain-of-custody)** | agent *claiming* a test ran that never ran — fabricated proof | SOUL.md:23-26; SKILL.md:60-68 |
| **RSI evidence ledger** | tautological self-proof; overfit-to-the-ruler | commits 81c9ac7, 739ad2d |
| **Execution-grounded war room** | sycophancy / conformity cascades in multi-agent review | execution-grounded-warroom.md:37-43 |
| **Policy enforcer** | Otto asking permission instead of acting | policy-enforcer-redesign.md:3-18 |

**LUX/POPDD are a two-language ecosystem, not duplicates:** TS chain = `lux` + `popdd-ts`;
Py chain = `lux-spec-py` + `popdd-py` + `lux-spec-cli` (CLI gate over both). Live deployments:
`signalengine/.lux/`, `prospector/.lux/`. Zero redundancy between the TS and Py sides.

---

## 3. THE CANONICAL LIVE SPINE (what is actually running — ground truth)

`launchctl list | grep hermes` + `lsof`:

```
ALIVE:  ai.hermes.cockpit   PID 24644  FastAPI 127.0.0.1:8801  ← the ONE live Telegram front door (webhook)
        ai.hermes.ngrok     PID 23923  tunnels :8801 to public ← Telegram reaches us through this
        ai.hermes.otto-server PID 24648 AI agent 127.0.0.1:8802 ← cockpit relays free-text here
        ai.hermes.coordinator PID 658  task brain → coordinator.db (148 done / 16 escalated)
PERIODIC (cron, ok): health-watchdog 15m, 17 cron jobs green
DEAD-ON-PURPOSE: ai.hermes.gateway (the OLD Telegram front door — replaced by cockpit)
FENCED/IDLE: ai.hermes.rsi (daily 04:30, needs OFF_SWITCH armed)
```

Databases are **three different concerns, not duplicates**: `coordinator.db` (task lifecycle,
live), `state.db` (37 MB, AI conversation/session memory, live), `kanban.db` (designed-but-
unused dispatch store, 0 tasks, dead since Jun 17 — a scaffold for the future sentinel
coordinator, harmless).

**Two coordinators are complementary:** `~/.hermes/scripts/coordinator.py` (103 KB, PID 658,
THE production brain) vs `sentinel-loop/sentinel/coordinator.py` (7 KB skeleton, tests only,
its own docstring admits "KanbanDB does not yet expose pending_tasks()"). The repo one is a
WIP replacement, not a rival.

---

## 4. THE ONE DANGEROUS TRUTH — the estate is mid-migration and split-brained

The estate was deliberately migrating its Telegram front door **from the gateway (full-agent
long-poll) to the cockpit (structured DevOps webhook)**. The migration is **half-done**:

- The cockpit got the **dashboards and slash commands** (`/dashboard /daemon /killed /logs`…)
  — all working (menu.py).
- The cockpit **never got the estate-control callback handlers.** Every control button —
  `task:approve:{id}`, `task:cancel`, `estate:pause`, `estate:resume`, `estate:restart`,
  `estate:system_fuel`, `update_prompt:{y/n}` — is handled **ONLY** in the dead gateway at
  `~/.hermes/hermes-agent/gateway/platforms/telegram.py:4206-4388`. Grep for these in
  `sentinel/cockpit/server.py` → **zero hits.**

**Consequence (proven, not hypothetical):** the coordinator keeps sending approve/pause
buttons to Telegram (`coordinator.py:108-138`); they land at the cockpit; the cockpit has no
handler and **silently drops them.** Right now:

- **16 tasks are stuck `escalated`** with no working approve/reject path from the phone.
- **1 Prospector mission has been blocked since ~Jun 21** with no remote unblock.
- **There is no working emergency-STOP from Telegram** — `estate:pause` is dead. A founder on
  a phone cannot halt estate spend.

This — not the file sprawl — is the heads-will-roll problem. "Where does it begin and end" is
confusing **because it is genuinely half-migrated**, not because it's badly designed.

---

## 5. THE HALLUCINATION POSTURE (honest answer to "is it perfect from Telegram?")

There **is** a real cryptographic proof system (POPDD receipts, HMAC-signed evidence ledger,
adversarial completion verifier). But its enforcement is **scoped**:

- **Enforced in code — but audit-time, scheduled, fenced:** `evidence_verify.py` independently
  re-derives verdicts and HMAC-signs PASS, runs daily 04:30 via `rsi-autorun.sh`, fenced behind
  `OFF_SWITCH`. The verifier prompt is deliberately excluded from self-tuning (protects the
  gate). Task *completion* is gated by an adversarial verifier (`coordinator.py:667-675`) — it
  already caught and rejected 8 fabricated "Hello Otto" completions (that's why they escalated).
- **Instruction-only — no code gate — for conversational answers:** when you ask Otto a
  free-text question from Telegram, proof-of-claim is a *prompt* (SOUL.md:36-46), not a gate.
  The synchronous gate that would force claims through a probe (`hermes_claims.py:18-21`) is
  **built but not wired** (needs a Stop/PostToolUse hook that "has not landed").

**So today, from Telegram:** structured commands (`/dashboard`, `/daemon`, estate-ground-truth
probe) = trustworthy ground truth. **Free-text answers from Otto = LLM-generated, ungated,
hallucination-possible.** Closing this is requirement #3 of the North Star.

**Routing bug feeding the problem:** conversational messages are being injected into the
coordinator's *automation* queue (server.py:498-501), so "what is the goal of the day?" becomes
a fake automation task with fabricated acceptance tests. Conversational text must route to
`_call_otto()`, never to `coordinator.inject()`.

---

## 6. WHAT WE NEED TO CONVERGE (the gap list, ranked)

**P0 — restore operator control (finish the migration into the live cockpit):**
1. Port `task:approve` / `task:cancel` callback handlers into `cockpit/server.py` → unblock the
   16 escalated tasks from the phone.
2. Port `estate:pause/resume/restart` → real emergency STOP + a `[⏸ Pause]` button on
   `/dashboard`. (`coordinator.set_estate_paused()` already exists, `coord:1565`.)
3. Add a `/tasks` (escalated + approve/reject) and mission unblock path (needs a ~10-line
   `unblock_mission()` in coordinator).

**P0 — disarm the landmine (do this first, it's free):**
4. The gateway plist is `RunAtLoad=true`/`KeepAlive=true` but unloaded. One `launchctl load`
   (or a reboot/restore) starts it, it calls `deleteWebhook`, and the cockpit goes **silently
   deaf**. Disable the plist (`<key>Disabled</key><true/>` or rename `.DISABLED`) until the
   gateway's control handlers have been ported into the cockpit.

**P1 — close the hallucination hole:**
5. Wire `hermes_claims.py` / the estate-ground-truth probe into Otto's free-text answer path so
   estate questions answer from live db/config, not LLM memory.
6. Fix the conversational-vs-task routing (server.py:498-501).

**P1 — total visibility the cockpit doesn't yet have:** `/cron` (22 jobs, 1 erroring since
Jun 23 — invisible today), `/fuel` (token/budget spend — invisible), satellite status for
signalengine + lux (only Prospector is wired).

**P2 — capability currently switched off:** `COCKPIT_EXECUTION_ENABLED` is unset, so all
git/docker/npm dispatcher actions return `blocked`. Turn on once the control plane is single
and proven. (`systemctl_*` actions are macOS-dead — ignore.)

**Housekeeping landmines:** `cockpit-daemon.sh`/`ngrok-daemon.sh`/`otto-daemon.sh` are
UNTRACKED in `~/.hermes/.git` (a restore loses the daemon launchers — commit them). `.env` is
correctly `600` + gitignored (safe). `glob` NameError silently breaks audit-report attachment
(otto-inbound/__init__.py:352).

---

## 7. THE ONE RULE (carve in stone)

**Exactly one process may own the Telegram bot token at a time.** Telegram delivers to a
webhook *or* a poller, never both. The cockpit (webhook) is canonical. The gateway and
`reliable_otto.py` are pollers that call `deleteWebhook` on startup — starting either one while
the cockpit runs makes the cockpit silently deaf. Never run two.

---

## 8. LOAD-BEARING vs DEAD (so nobody retires the wrong thing)

**DO NOT TOUCH:** `~/.hermes/scripts/coordinator.py`, `coordinator.db`, `state.db`,
`cockpit/server.py`, `otto_server.py` + its plist, `.env`, the whole LUX/POPDD pair set.
**GENUINELY DEAD (safe to archive, not delete blindly):** `kanban.db` (future scaffold),
`reliable_otto.py` (alt transport, fallback-by-design — keep but never start while cockpit is
up). **DECISIONS STILL OPEN (ratify before acting):** (a) finish migration into cockpit vs
revive gateway as the single door; (b) make `~/.hermes/.git` canonical vs consolidate into the
sentinel-loop repo. No code moves until these are chosen.
