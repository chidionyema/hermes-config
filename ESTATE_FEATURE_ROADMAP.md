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
| Single live Telegram front door (webhook) | cockpit PID 24644, `uvicorn sentinel.cockpit.server` :8801 | ✅ live |
| Public reachability | ngrok PID 23923 → :8801 | ✅ live |
| Dashboards + slash commands + nav | `menu.py:440-478` (`/dashboard /daemon /killed /logs`) | ✅ live |
| Otto free-text chat relay | `server.py:109 _call_otto()` → otto-server PID 24648 :8802 | ✅ live |
| Task brain w/ investigate-before-escalate | `coordinator.py:1361-1366` (escalate REFUSES w/o diagnosis) | ✅ live |
| Adversarial completion gate | `coordinator.py:667-675` — caught & rejected 8 fabricated completions | ✅ live |
| Layered defense (sentinel/watchdog/fiscal sentry) | North Star §2 table, all cited | ✅ live |
| LUX/POPDD proof chains (TS + Py) | deployed `signalengine/.lux/`, `prospector/.lux/` | ✅ live |
| Signed evidence ledger (audit-time) | `evidence_verify.py`, HMAC key `meta/.evidence_verifier_key` | ⚠️ fenced (see §2) |

## 2. WHAT IS BUILT BUT NOT WIRED (the convergence debt)

| Capability | Why it's dark | Evidence |
|---|---|---|
| **Estate control buttons** (approve/cancel/pause/resume/restart/prompt-update) | Handlers exist in the **dead gateway**, never ported to the live cockpit | gateway: `telegram.py:4082,4115,6247,4349,3167`; cockpit dispatch has no branch: `menu.py:440-478` |
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
