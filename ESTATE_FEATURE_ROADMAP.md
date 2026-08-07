# ESTATE FEATURE ROADMAP — principal review of the North Star

*Independent verification 2026-06-25. Companion to `ESTATE_NORTH_STAR.md`. Every line is backed
by `file:line` or command output re-run on disk today. This is a guideline; no code has moved.*

---

## 0. VERDICT ON THE WAR-ROOM REPORT

The North Star holds up under independent re-verification. **One correction and one nuance:**

- **CORRECTION (mine, not the report's):** an intermediate grep for the literal string
  `task:approve` returned zero hits in the gateway and looked like the report was wrong. It is
  not. The gateway matches the callback by **prefix** — `telegram.py:4082 if data.startswith("task:")`,
  approve branch at `telegram.py:4115 if choice == "approve"` — so the compound literal never
  appears as text. The report's claim ("control callbacks live in the gateway, zero in the
  cockpit") is **confirmed**.
- **CONFIRMED — the split-brain is real:** the live cockpit dispatcher `menu.py:handle_callback`
  (`menu.py:437`) has branches for nav/dashboard prefixes only — `nv: ac: dx: dh: dg: da: ds:
  dk: di: dz: dl: dr:` (`menu.py:440-478`). **No `task:` / `estate:` / `update_prompt:` branch
  exists.** The coordinator sends exactly those buttons (`coordinator.py:120-121` →
  `task:approve:{id}` / `task:cancel:{id}`; `:146-157` → `estate:pause/resume/restart/refresh/
  system_fuel`). Result: button taps fall through and are silently answered. Proven, not hypothetical.

Everything else in §3–§7 of the North Star I re-checked today still reads true (see §3 below).

---

## 1. WHAT WE HAVE TODAY (working ground truth)

| Capability | Evidence | State |
|---|---|---|
| Telegram front door — **the GATEWAY, by long-poll** | `ai.hermes.gateway` loaded, `hermes_cli.main gateway run --replace`, up since 7 Aug 06:59. Listens on NO port; holds 2 ESTABLISHED TCP to `149.154.166.110:443` (Telegram). Probe: `launchctl list \| grep gateway; lsof -nP -a -p <pid> -i` | ✅ live (2026-08-08) |
| Cockpit webhook front door (`:8801`) | `uvicorn sentinel.cockpit.server`. Plist present, **NOT loaded**; 8801 CLOSED. Probe: `launchctl list \| grep cockpit; nc -z 127.0.0.1 8801` | ⛔ DOWN (2026-08-08) |
| Public reachability (ngrok → :8801) | Plist present, **NOT loaded**. Only ever needed by the webhook door above; long-poll needs no inbound path. Probe: `launchctl list \| grep ngrok` | ⛔ DOWN — not required while the gateway long-polls |
| Dashboards + slash commands + nav | `menu.py:440-478` (`/dashboard /daemon /killed /logs`) — these are **cockpit** handlers, so they are dark with the cockpit. Whether the gateway serves its own equivalents is UNVERIFIED (see §2 note). | ⚠️ built, dark on this path |
| Otto free-text chat relay | `server.py:109 _call_otto()` → otto-server `:8802`. Plist present, **NOT loaded**; 8802 CLOSED. Its only caller is the cockpit, which is also down — loading it alone would start a service with no caller. Probe: `launchctl list \| grep otto; nc -z 127.0.0.1 8802` | ⛔ DOWN (2026-08-08) |
| Task brain w/ investigate-before-escalate | `coordinator.py:1361-1366` (escalate REFUSES w/o diagnosis) | ✅ live |
| Adversarial completion gate | `coordinator.py:667-675` — caught & rejected 8 fabricated completions | ✅ live |
| Layered defense (sentinel/watchdog/fiscal sentry) | North Star §2 table, all cited | ✅ live |
| LUX/POPDD proof chains (TS + Py) | deployed `signalengine/.lux/`, `prospector/.lux/` | ✅ live |
| Signed evidence ledger (audit-time) | `evidence_verify.py`, HMAC key `meta/.evidence_verifier_key` | ⚠️ fenced (see §2) |

> **Corrected 2026-08-08 — and the correction is an INVERSION, not a downgrade.** These rows read
> `✅ live` citing cockpit PID 24644, ngrok 23923 and otto-server 24648. All three PIDs are gone, none
> of those three labels is loaded, and 8801/8802 are CLOSED. But Telegram is NOT dark: the loaded
> `ai.hermes.gateway` (pid 1412, up since 7 Aug 06:59) holds two ESTABLISHED connections to Telegram
> and listens on no port — it **long-polls**. So the door this document calls "the dead gateway" in §2
> is the door actually taking messages, and the door it called live has been down.
>
> Two lessons, both mechanical: a **PID is stale the moment a process restarts**, so the evidence
> column now carries the **probe command** instead of a number that rots; and "is the front door up?"
> was answered by checking the process we *expected* to serve it, which reports DOWN for a door that
> works. Ask what is listening / connected, not whether the named process is alive. Estate-wide
> version: `bash ~/.hermes/scripts/verify_estate.sh`.

## 2. WHAT IS BUILT BUT NOT WIRED (the convergence debt)

| Capability | Why it's dark | Evidence |
|---|---|---|
| **Estate control buttons** (approve/cancel/pause/resume/restart/prompt-update) | Believed dark because the handlers live in "the dead gateway". **That premise is now falsified** — see the §1 note: the gateway is the LOADED, Telegram-connected process and the cockpit is the one that is down. Whether these handlers are reachable today is therefore UNVERIFIED, and the honest next step is to send one control command through Telegram and observe, not to port anything. | gateway: `telegram.py:4082,4115,6247,4349,3167`; cockpit dispatch has no branch: `menu.py:440-478`; liveness: `launchctl list \| grep gateway` |
| **Inline hallucination gate** | `hermes_claims.py` referenced only by a test; no Stop/PostToolUse hook | only prod ref is `tests/test_dropped_ball.py:7` |
| **Signed-claim enforcement** | `evidence_verify.py` works but `OFF_SWITCH` absent → daily run skips; not in cron manifest | `rsi-autorun.log` "OFF_SWITCH absent — disarmed" since 2026-06-21 |
| **Execution dispatcher** (git/docker/npm) | `COCKPIT_EXECUTION_ENABLED` unset → every action returns `blocked` | `dispatcher.py:130` requires `== "1"`; shell shows `[]` |

## 3. WHAT WE NEED TO BUILD (net-new, missing entirely)

- **`/tasks` view** — list 16 escalated tasks + per-task approve/reject inline. (Cockpit has no task view at all.)
- **Mission unblock path** — `unblock_mission()` (~10 lines) in coordinator; 1 Prospector mission blocked since ~Jun 21.
- **`/cron` visibility** — 22 jobs, 1 erroring since Jun 23, invisible from Telegram today.
- **`/fuel` visibility** — token/budget spend not surfaced anywhere on the phone.
- **Satellite status** — signalengine + lux not wired into the cockpit (only Prospector is).
- **Conversational↔task routing fix** — `server.py:498-506` injects plain chat into the coordinator
  automation queue, so "what's the goal today?" becomes a fake task with fabricated acceptance tests.
  Chat must route to `_call_otto()`, never `coordinator.inject()`.

## 4. LANDMINES TO DEFUSE (not features — safety)

1. **Gateway plist is armed.** `ai.hermes.gateway.plist` has `RunAtLoad=true` + `KeepAlive=true`
   (confirmed) but is currently unloaded. One `launchctl load` / reboot / restore starts it, it
   calls `deleteWebhook`, and the cockpit goes **silently deaf**. **Disable the plist first — zero risk.**
2. **Daemon launchers untracked.** `cockpit-daemon.sh` / `ngrok-daemon.sh` / `otto-daemon.sh`
   untracked in `~/.hermes/.git` — a restore loses the launchers. Commit them.

---

## 5. THE RANKED ROADMAP (what to do next)

**Gate 0 — free + zero-risk, do regardless of any decision:**
- [ ] Disable the gateway plist (`<key>Disabled</key><true/>` or rename `.DISABLED`).
- [ ] Commit the three daemon launcher scripts into `~/.hermes/.git`.

**P0 — restore operator control (the heads-roll item):**
- [ ] Add `task:` + `estate:` + `update_prompt:` branches to `menu.py:handle_callback`, calling the
      coordinator's already-existing `set_estate_paused()` (`coordinator.py:1565`) etc. → unblocks
      the 16 escalated tasks and gives a real emergency STOP from the phone.
- [ ] `/tasks` view (escalated + approve/reject buttons).
- [ ] `unblock_mission()` in coordinator + a mission-unblock button.

**P1 — close the hallucination hole (North Star non-negotiable #3):**
- [ ] Fix conversational-vs-task routing (`server.py:498-506`).
- [ ] Wire `hermes_claims.py` / ground-truth probe into Otto's free-text answer path.

**P1 — total visibility:**
- [ ] `/cron`, `/fuel`, satellite status (signalengine + lux).

**P2 — turn execution on:**
- [ ] Set `COCKPIT_EXECUTION_ENABLED=1` once the control plane is single and proven.

---

## 6. TWO DECISIONS THAT GATE EVERYTHING (founder's call — ratify before code moves)

The entire P0 sequence above assumes answers to these. Per the proof-of-claim rule, no code moves
until they are chosen, not assumed:

- **(A) Single Telegram door:** finish the migration **into the cockpit** (recommended — it's the
  live, webhook-secured, self-healing front door; reviving the gateway re-introduces the
  two-poller `deleteWebhook` landmine) — *vs* revive the gateway and retire the cockpit.
- **(B) Source of truth:** bless **`~/.hermes/.git` as canonical** (recommended — matches what runs,
  least disruption) *vs* consolidate into the `sentinel-loop` repo (cleaner, but a live-daemon
  migration with restart risk).
