# 🏛️ HERMES / OTTO ESTATE — COMPLETE GROUND-TRUTH AUDIT
**Captured:** 2026-06-21 ~10:40 BST · **Host:** chidis-MacBook-Pro · Darwin 23.5.0 x86_64
**Method:** 7 parallel read-only recon probes (launchd · gateway/Telegram · coordinator/DBs · cron · scripts/skills · repos · war-room) + live duel result.
**Scope:** every daemon, plugin, command, schedule, script, skill, spec, repo, database, and agent. Nothing omitted.

---

## 0. EXECUTIVE SUMMARY — WHERE THINGS ARE GOING WRONG

You asked for a *heavenly, hands-off estate you run from Telegram*. The machinery to do that **exists and is large** (155 scripts, 23 cron jobs, 4 designed daemons, a proven war-room, a full task-lifecycle coordinator). The reason it doesn't *feel* heavenly is not missing features — it's **five disconnections between the machinery and the outcome**:

| # | Root problem | Evidence | Effect you feel |
|---|---|---|---|
| **R1** | **Observability + self-improvement daemons are DOWN.** watchdog, progress, rsi launchd agents are *unloaded* (PID 0). | §1 | No independent health monitor; no RSI loop; "is it alive?" can only be answered by the thing being asked. |
| **R2** | **The autopilot is PARKED.** Coordinator is alive but every tick does `advanced=0`. All 33 tasks are terminal (23 escalated, 10 done). **Zero operator projects ever shipped.** | §3 | You inject work and nothing visibly happens. |
| **R3** | **Diagnosis fails on real requests.** Vague injects ("audit the estate", "who is handling this?") produce an EMPTY spec → executor can't act → escalates forever. Your own messages are stuck escalated right now. | §3 | Telegram feels like a black hole — tasks go in, silence comes out. |
| **R4** | **The estate never speaks first.** `gateway_notify_interval: 0` + otto-dispatch paused = pure pull model. Nothing pings you. | §2,§4 | Feels "light" — you must know the magic command to get anything back. |
| **R5** | **The proven engine isn't wired in.** The war-room (now 5/5 vs 0/5) is **test-only**; the live coordinator diagnoses with a single `strategist` role — the very step that's producing empty specs. | §7,§3 | Your best asset isn't doing the actual work. |

**One-line diagnosis:** *It's a Ferrari engine with the driveshaft disconnected.* The interface is actually rich (31+ Telegram commands); the loop behind it is parked, mute, and routed through its weakest link.

Plus today's pain — **the macOS "Python wants access" prompt loop** — was a symptom of **unsigned interpreters** (uv CPython + Homebrew framework `Python.app`s). Fixed this session (ad-hoc signed; `scripts/sign-interpreters.sh`), but it's a sign of the same theme: lots of moving parts, fragile seams.

**The good news:** nothing here is fundamentally broken-by-design. Five wiring fixes (Part 9) turn this from parked to hands-off.

---

## 1. DAEMONS, LAUNCHD & LIVE PROCESSES

### LaunchAgents registered
| Label | Loaded | Runs | Schedule | State |
|---|---|---|---|---|
| **ai.hermes.gateway** | ✅ | `hermes_cli.main gateway run --replace` (uv py3.11) | KeepAlive | LIVE pid 6377, ~12h, clean |
| **ai.hermes.coordinator** | ✅ | `coordinator.py daemon` (Homebrew py3.14) | KeepAlive, 60s tick | LIVE pid 7793, ~8h, clean |
| **ai.hermes.watchdog** | ❌ **UNLOADED** | `estate_watchdog.py` | 300s | **DOWN** — no independent health monitor |
| **ai.hermes.progress** | ❌ **UNLOADED** | `progress-snapshot.sh` | hourly | **DOWN** — autonomy trend not accruing |
| **ai.hermes.rsi** | ❌ **UNLOADED** | `rsi-autorun.sh` | 04:30 daily | **DOWN** — self-improvement loop off |
| com.prospector.scheduler | ✅ | prospector candidate gen | KeepAlive, 2h | LIVE pid 7714 |
| com.prospector.watchdog | ❌ | prospector watchdog | 900s | unloaded |
| com.tie.ai-review | ❌ (exit 78) | TIE review orchestrator | 02:00 | disabled (DEEPSEEK_API_KEY empty) |
| com.haworks.continuous-review | ❌ (exit 1) | haworks-review | 6h | broken binary |
| com.haworks.test-coverage | ❌ (exit 1) | haworks-testcov | 6h | broken binary |

### Live processes of interest
| PID | %CPU | Uptime | What |
|---|---|---|---|
| 6377 | 0.0 | 12h | Gateway daemon (healthy) |
| 7793 | 0.0 | 8h | Coordinator daemon (healthy, but parked — see §3) |
| 7714 | 0.0 | 8h | Prospector scheduler |
| 78846 | 0.6 | 23h | Prospector Streamlit UI (localhost:8601) — long-lived |
| 20492–94 | 0.0 | ~22h | py3.12 multiprocessing workers (idle) |

### ⚠️ Issues
- **R1 root:** 3 estate daemons (watchdog/progress/rsi) are unloaded. `gateway.error.log` is 1.4 MB of Telegram reconnect/httpx warnings (external flakiness, non-fatal).
- Gateway & coordinator have churned PIDs (97659→98616→6377; 4651→6379→7793) — restarts from this session's signing work; both now stable.
- TIE + Haworks scheduled jobs are dead (missing keys / missing binaries) — low priority.

---

## 2. GATEWAY, PLUGINS & TELEGRAM COMMAND SURFACE

**config.yaml:** primary `deepseek-v4-pro`, fallback `MiniMax-M3`; `gateway_notify_interval: 0` (**all proactive notifications OFF**); cron dispatch in-gateway 60s; one plugin enabled: **otto-inbound** (`pre_gateway_dispatch`).

**Flow:** Telegram → gateway → `pre_gateway_dispatch` (otto-inbound) → intent match → handler → fire-and-forget ack. Any error → `{"action":"allow"}` so messaging never breaks.

### The Telegram surface is NOT light — 31+ commands across 8 classes:
- **Self-knowledge:** `Otto what model are you?`, `Otto status/health/are you alive?`
- **Cockpit reads:** `Otto help`, `brief`, `backlog`, `decisions`, `chores`, `reflect`
- **Introspection:** `Otto rsi status`, `diagnostics`, `why [id]`, `remember <topic>`
- **Approvals:** `Otto approve <id>`
- **Missions/autopilot:** `Otto launch <name>: <goal>`, `missions`, `mission <ref>`, `resume <id>`, `abort <id>`
- **War room:** `Otto war room: <question>`
- **Big switches:** `Otto pause/resume the estate`, `restart the gateway`, `arm/disarm self-improvement`
- **Task injection (fallthrough):** `Otto, <anything>` → coordinator

### ⚠️ Gaps (why it *feels* light despite 31 commands)
- **No proactive push** (R4): nothing pings you; `decisions`/`chores`/escalations must be pulled.
- Missing pulls that exist as data but aren't exposed: **cost/spend**, **project portfolio**, **escalation history**, **task search**, **retry**, **evidence detail**, **cron visibility**.
- No inline approve/reject **buttons** (coordinator has `send_telegram_buttons()`, otto-inbound doesn't call it).
- Query-gating (`≤6 words OR ends with ?`) can swallow phrasings like "Otto give me a brief".
- No "coordinator is down" alert path; no task-timeout warning.

---

## 3. COORDINATOR, TASKS & DATABASES  ← **the heart of the problem**

**coordinator.py** = persistent task-lifecycle brain. CLI: `daemon, once, inject, approve, brief, backlog, decisions, chores, health, progress, metrics, digest, missions, evidence, requeue-transient`. Lifecycle: `open→diagnosed→executing→verifying→done`, with `escalated` / `awaiting_approval` (founder fence). **Investigate-before-escalate is structurally enforced** (escalate refuses without a prior diagnosis event — good).

### Databases
| DB | Table | Rows | Note |
|---|---|---|---|
| **coordinator.db** | tasks | **33** | **23 escalated (70%), 10 done (30%), 0 active** |
| | events | 549 | full audit trail |
| | missions | 1 | Prospector — **blocked 3 days** |
| | progress_snapshots | 14 | latest **autonomy 30.3%** |
| | evidence | 1 | single PASS proof (known-class) |
| | telemetry | 111 | total spend ~$0.017 |
| kanban.db | tasks | 0 | gateway queue (drained into coordinator) |
| state.db | messages | 1581 / 64 sessions | chat history |

### The actual stuck work (your injects)
- **`b43a9c4f` "who is handling this?"** — escalated. Spec EMPTY (`root_cause:"", steps:[]`). Diagnosis failed → executor couldn't act.
- **`67da3d13` "audit the estate and full workflow"** — escalated, same empty-spec failure, no heartbeat 2h.
- **`c3dc3d62`/`5b65dd3e`/`b7b2fb42` signalengine pytest hangs** — 3 dupes, requeued transient 3× → escalated.
- **`db8745ca` Prospector ▸ clone repo** — executor *correctly refused* a destructive `rm -rf prospector` spec (strategist confused your real prospector project with the public linter). Blocked 3 days, no ping to you.
- **~19 housekeeping escalations** — health/repo/signal watchdogs, 1–7 days stale, requeued then abandoned.

### ⚠️ Issues
- **R2:** every tick `advanced=0` because `list_active()` is empty — all tasks are terminal. The daemon runs but has no runway.
- **R3:** strategist produces empty specs on vague input instead of bouncing for clarification → infinite escalation loop. **This is the single highest-leverage bug.**
- **Autonomy 30% is real but 100% housekeeping** — zero operator projects shipped.
- Executor refusals (often correct!) never surface to you as a Telegram ping.
- `SOUL.md` mission ("Protect → Prove → Ship") vs reality: protecting & proving, **not shipping**.

---

## 4. SCHEDULED JOBS (CRON FLEET) — 19 active / 4 paused

**High-freq (5–15m):** queue-curator, signal-engine-daemon-watchdog, pytest-orphan-cleanup, health-watchdog, improvement-probe.
**Mid (30–60m):** idle-continuous-learning, idle-curiosity, hermes-config-auto-push, prospector-daily-generation.
**Long (2h–weekly):** repo-health-check (2h), proving-ground-audit (2h), estate-inventory-audit (06:00), daily-strategist-audit (08:00), **morning-briefing (09:00 — the one user-facing ping)**, daily-self-reflection (18:00), summarize-activity (18:00), uncommitted-watch (6h), weekly-lux-verify (Sun 00:00).
**Paused (with reasons):** otto-dispatch (timeout 120s, 2026-06-20), goal-of-the-moment (timeout risk), otto-improvement-pulse (superseded by evidence ledger), Run-health-check (superseded by repo-health-check).

### ⚠️ Issues
- **otto-dispatch paused = the only proactive escalation relay is OFF** (R4). It timed out at 120s; paused rather than fixed.
- Only **1** user-facing Telegram job (morning-briefing). Everything else is silent/local.
- Possible overlap/thrash: improvement-probe + health-watchdog (both 15m); idle-learning + idle-curiosity (both 30m).
- Prospector generates ~20 candidates/hour (480/day) — verify that's intentional token spend.

---

## 5. SCRIPTS, SKILLS & SPECS — 155 scripts / 1 skill / 14 specs

**Scripts:** 132 .py + 23 .sh = 155 (58 entry-points run by daemon/cron/hooks, 97 helpers). Groups: coordinator/core, dispatch/triage, watchdog/health (3 overlapping liveness detectors), self-improvement pipeline (8-phase), RSI, reflection, estate inventory/drift/optimization/remediation, proving-ground, memory, war-room, utilities. **Zero broken references; zero orphan entry-points.**

**Skills:** just **1** — `graphify` (`/graphify`, folder → knowledge graph). *(Note: the global CLAUDE.md references graphify only; the estate's "skills" are really the cron-invoked otto-operating-model agents.)*

**Specs (14):** `execution-grounded-warroom.md`, `policy-enforcer-redesign.md`, and `otto-system/00-MASTER.md` … `10-exponential-self-improvement.md` (the full Phases 0–5 design + correction-learning, dispatch-gate, memory-retrieval, idle-consolidation, self-regression, gap-finding, exponential-self-improvement-with-off-switch).

**Reports:** heavenly-estate-architecture-2026-06-20, daily strategist audits, learning-proof-warroom, estate inventory/drift/optimization, cron-failure-rootcause, backlog.

### ⚠️ Issues
- Consolidation candidates: 3 watchdog scripts → 1; 10+ `*-probe` receipts → 1 template; otto-correction cluster → 1 module.
- Strategist/Executor roles routable but not fully wired (Phase 3+).
- Sprawl is *acceptable* for the ambition, but the entry-point:helper ratio (58:97) is a lot of surface to keep alive.

---

## 6. REPOSITORIES & GIT STATE — 16 repos, ~1,680 uncommitted (93% backup noise)

**Real active work (~120 files):**
| Repo | Branch | Uncommitted | Risk |
|---|---|---|---|
| signalengine | salvage/c9-c10-m7-relocate | 20 (12 staged) | 🟡 staged work + 3 commits unpushed |
| haworks-platform | **main** | 41 | 🟠 widespread refactor uncommitted **on main** |
| .hermes | main | 21 (16 staged) | 🟡 3 commits unpushed |
| the-introduction-exchange | feat/e33-004-kycgate | 8 + orphan worktrees | 🟠 9 days stale |
| prospector | launch-hardening-2026-06-18 | 8 | 🟢 |
| ritualworks | port/queries-sweep | 5 | 🟠 43 days stale |
| lux | main | 3 | 🟢 |

**Backup/ancient noise (~1,560 files):** `modeltrainer_backup/modeltrainer` (**1,559** — a 2023 backup mid-deletion), vault-101 (2023), vault-201 (2024), haworks (2025).

### ⚠️ Issues
- **3,509 "uncommitted files" headline is misleading** — 93% is the modeltrainer backup. Real at-risk work is ~120 files.
- haworks-platform 41 files **on main** (should be a feature branch).
- signalengine + .hermes have **commits unpushed** (off-machine backup gap).
- TIE has orphaned `.worktrees/` (e11-mmx, notifications, fix-ratelimit…) never cleaned up.

---

## 7. MULTI-AGENT WAR ROOM & MODEL ROUTING — proven, but not wired in

**route.py roles (ALL-DIRECT, never OpenRouter):**
| Role | Primary | Fallbacks |
|---|---|---|
| Coordinator | DeepSeek deepseek-v4-flash | Claude CLI |
| Strategist | Claude CLI (subscription OAuth, API key unset) | AGY CLI → deepseek-v4-pro |
| Executor | MiniMax-M3 | DeepSeek-flash → Gemini-2.5-flash |

Rotation on 429/503/timeout/connection/billing-400; no rotation on genuine malformed 400; `RouteExhausted` with per-provider audit trail. Founder fence enforced (coordinator.py ~887–895): money/identity/contract pause at `awaiting_approval`.

**warroom.py** = 4-stage execution-grounded debate: (0) Gemini allocates 4 exclusive paths; (1) 4 personas generate in parallel (Empiricist=Claude, Red-Team=AGY, Lateral=DeepSeek, Pragmatist=MiniMax); (2) anonymized cross-review where any flaw claim **must ship a sandboxed test printing `VULN_PROVEN`/exit 42** (Docker `--network none` or `sandbox-exec`); (3) chairman synthesizes evidence-gated final code. Worktree-isolated; signalengine live tree never mutated.

### Latest CI Duel — 2026-06-21 (noise-resistant rerun)
**Mutate mode, 5 targets × 3 trials, majority vote:**
```
Single Frontier Model:        0/5  (0.0%)
Execution-Grounded War Room:  5/5  (100.0%)   ✅ +100 pts
```
Per-target: cost_model `<`→`<=` (S 1/3, WR 2/3); cpcv (S 0/3, WR 3/3); strategies/base `and`→`or` (S 1/3, WR 2/3, dissent 0.52); numeric (S 0/3, WR 3/3); promotion_gate (S 0/3, WR 3/3). **This reverses June's honest n=4 TIE.**

### ⚠️ Issues — read the verdict honestly
- **The control is MiniMax-M3 zero-shot (the cheap executor), not the best single model.** The war-room *contains* Claude CLI. So this proves **"4-model ensemble incl. Claude > MiniMax alone"**, not "ensemble > best frontier model." A fair test pits the war-room against **Claude alone**. Until then, +100 is real but **over-claims**.
- **War-room is test-only** (R5): not wired into the coordinator's live task loop. Real diagnosis uses the single `strategist` role — the one producing empty specs in §3.
- Fallback chains never fault-tested under a real live 429 mid-task.
- AGY identity ambiguous (eval substitutes Gemini for AGY — "Gemini is AGY's backend").
- CLI timeout asymmetry: eval caps 75s, production 300s → one war-room target can burn 900s.

---

## 8. DATA STORES & IDENTITY (consolidated)
- **state.db:** 64 sessions / 1,581 messages (+ FTS). **coordinator.db / kanban.db:** see §3. **SOUL.md:** 4,982 chars — archetype "LUX, the Celestial Coordinator," mandate "Protect → Prove → Ship."
- **meta/:** evidence ledger (HMAC-signed, 1 proof, 10h old), proofs/, metrics.jsonl (hourly, improvement-velocity **0.0**), snapshots/ (hourly), rsi_evalsets/, warrooms/, launchd/ plists, ESTATE_PAUSED / OFF_SWITCH control files.

---

## 9. WHAT TO FIX — prioritized roadmap to "hands-off from Telegram"

**P0 — Restart the heart (today, ~30 min, reversible)**
1. Reload the 3 dead daemons: `launchctl load -w` watchdog, progress, rsi. (R1)
2. Fix R3 (the empty-spec loop): make the strategist **bounce vague tasks for one-line clarification via Telegram** instead of emitting an empty spec. This alone unsticks your real injects.
3. Surface executor refusals + escalations as a **proactive Telegram ping** (re-enable a hardened otto-dispatch with a real timeout, or have the coordinator notify on `escalated`). (R4)

**P1 — Wire the proven engine in (this week)**
4. Route coordinator *diagnosis of non-trivial tasks* through the **war-room** (or at least strategist→war-room on first verify-fail), instead of single-strategist. (R5)
5. Make the duel **fair**: control = Claude-alone, not MiniMax — then re-publish the verdict honestly.
6. Add the missing pulls: `Otto spend`, `Otto projects`, `Otto retry <id>`, inline approve/reject buttons.

**P2 — Hygiene & trust (ongoing)**
7. Git: archive `modeltrainer_backup` (kills 93% of the noise), move haworks-platform work to a branch, push the unpushed signalengine/.hermes commits off-machine.
8. Consolidate the 3 watchdogs + 10 probe receipts; retire dead TIE/Haworks launchd jobs.
9. Keep `sign-interpreters.sh` in the loop after every `brew/uv` python upgrade (today's TCC fix).

**The north star:** you inject → coordinator diagnoses (war-room on hard ones) → executes → verifies → **pings you only when it needs a decision or when it ships** → you tap approve. Today every one of those arrows except "inject" is broken or mute. P0+P1 reconnect them.

---
*End of audit. All 16 repos, 155 scripts, 1 skill, 14 specs, 23 cron jobs, 10 launchd agents, 3 databases, and the war-room verdict accounted for.*
