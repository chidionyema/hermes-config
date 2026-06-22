# Hermes Setup Audit — 2026-06-21

> Methodology: Every claim below was verified by reading the actual file or running
> an actual command, unless marked [INFERRED]. Captured at 10:10 BST.

## 1. Architecture

### Identity & Entrypoint

| Component | Status | Details |
|-----------|--------|---------|
| `ai.hermes.gateway` | **loaded** (PID 98616) | Kept alive by launchd; runs `gateway_preflight.py` |
| `ai.hermes.coordinator` | **loaded** (PID 4651) | Coordinator daemon; 60s cycle; agentic exec enabled; max 6 inflight |
| `ai.hermes.watchdog` | unloaded (status 0) | `estate_watchdog.py` every 300s — not active |
| `ai.hermes.rsi` | unloaded (status 0) | Scheduled at 4:30am daily — not active |
| `ai.hermes.progress` | unloaded (status 0) | Hourly progress snapshots — not active |

**⚠️ 3 of 5 launchd services are unloaded.** `watchdog`, `rsi`, and `progress` have plists on disk but are not running. No `otto`-prefixed launchd plists exist.

**Gateway preflight:** Runs `hermes_cli.main gateway run --replace` via the venv Python. Environment carries `OPENAI_API_KEY`, `OPENAI_BASE_URL` (OpenRouter), `HOME`, `PATH`.

**Zsh/Bash:** No Hermes/Otto/Gateway entries in `~/.zshrc`, `~/.bashrc`, or `~/.aliases`.

### Code Layout

`~/.hermes/` contains ~150 top-level items:
- **hermes-agent/** — full source tree (agent, gateway, tools, providers, skills, web, tui)
- **scripts/** — 85+ operational scripts (coordination, health, learning, dispatch)
- **skills/** — 29 skill categories (software-development, mlops, creative, etc.)
- **reports/** — audit reports, estate inventory, strategist audits
- **logs/** — 17M of structured and unstructured logs
- **queue/** — incoming/processed queues, dispatch dedup, pending digests
- **policies/** — 12 policy JSON files
- **recovery/** — backup/restore scripts, frozen requirements
- **meta/** — pipeline config, evidence verifier key, war rooms, RSI evalsets

## 2. Dependencies & Runtime

| Layer | Version |
|-------|---------|
| Python | 3.11.15 (hermes-agent venv) |
| Node.js | v26.3.0 |
| .NET | 9.0.101 |

### Model Configuration

```
Default model: deepseek-v4-pro (provider: deepseek)
Fallback: MiniMax-M3 (provider: minimax)
No disabled toolsets
Max turns: 60
Gateway timeout: 1800s (30 min)
API retries: 3
Tool use enforcement: auto
```

### Provider Credentials (from `auth.json`)

| Provider | Entries |
|----------|---------|
| openai-api | 1 |
| openrouter | 1 |
| anthropic | 1 |
| deepseek | 1 |
| minimax | 1 |
| gemini | 1 |
| copilot | 1 |

### .env Keys (23 total)
`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, `GEMINI_API_KEY`, `MINIMAX_API_KEY`, `OPENROUTER_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_HOME_CHANNEL`, `TELEGRAM_ALLOWED_USERS`, `RSI_SIGNING_KEY`, `EXA_API_KEY`, plus browser and terminal config keys.

## 3. State & Memory

| Artifact | Size | Details |
|----------|------|---------|
| `state.db` | 24M (+ 4M WAL) | 64 sessions, 1,557 messages |
| `logs/` | 17M | Gateway, coordinator, watchdog, reflection, audit logs |
| `policies/` | 48K | 12 policy files |
| `memories/MEMORY.md` | 3,078 chars | Agent memory |
| `memories/USER.md` | 2,097 chars | User profile |
| `SOUL.md` | 4,982 chars | Persistent soul file |
| `kanban.db` | on disk | 8 tables (tasks, events, runs, attachments) |
| `coordinator.db` | on disk | 9 tables (tasks, events, missions, milestones, telemetry, evidence) |

## 4. Integrations

### Platform Wiring
**Only Telegram is connected.** The channel directory shows:
- **Telegram:** 1 DM channel — "Chidi Onyema" (ID: 8868748055)
- **All others:** empty (Discord, WhatsApp, Slack, Signal, Matrix, SMS, Email, etc.)

### Gateway State
```
State: running
Active agents: 0
Telegram: connected
Exit reason: none
Restart requested: false
```

## 5. Cron Jobs

**22 total — 18 active, 4 paused — 0 never-run, 0 errors**

### Active Jobs (18)

| Job | Schedule | Script | Deliver |
|-----|----------|--------|---------|
| morning-briefing | Daily 9am | (LLM-driven) | origin |
| daily-strategist-audit | Daily 8am | (LLM-driven) | local |
| activity-summary | Daily 6pm | (LLM-driven) | local |
| weekly-lux-verify | Weekly Sun midnight | weekly-lux-verify.sh | local |
| hermes-config-auto-push | Hourly | auto-push.sh | local |
| uncommitted-watch | Every 360m | uncommitted-watch.sh | local |
| daily-self-reflection | Daily 6pm | daily_reflection.py | local |
| idle-continuous-learning | Every 30m | idle-learning-run.sh | local |
| improvement-probe | Every 15m | improvement-probe.sh | local |
| health-watchdog | Every 15m | watchdog-cron.py | local |
| repo-health-check | Every 120m | repo-health-check.py | local |
| estate-inventory-audit | Daily 6am | estate-full-run.sh | local |
| idle-curiosity | Every 30m | idle-curiosity.py | local |
| prospector-daily-generation | Hourly | prospector-run.sh | local |
| signal-engine-daemon-watchdog | Every 5m | signal-engine-daemon-watchdog.sh | local |
| proving-ground-audit | Every 120m | proving-ground.py | local |
| queue-curator | Every 5m | queue-curate.sh | local |
| pytest-orphan-cleanup | Every 5m | pytest-orphan-cleanup.sh | local |

### Paused Jobs (4)

| Job | Paused Reason |
|-----|---------------|
| health-check (`9ba1919c7386`) | Superseded by `repo-health-check.py` |
| improvement-pulse (`d2cb4cf8d9db`) | Superseded by evidence ledger |
| otto-dispatch (`f0b2079864c5`) | — |
| goal-of-the-moment (`8b3beb82ae6e`) | — |

### Script Operationality
All 17 `no_agent` cron scripts verified — every one has an entry point (`#!/` shebang or `if __name__`). ✅

**Note:** One paused job (`9ba1919c7386`) had an inline shell command rather than a script file — this is expected since it was superseded.

## 6. Task Lifecycle (Inferred from running config)

1. **Message arrives** via Telegram → Hermes gateway (PID 98616) receives webhook
2. **Session created** — entry in `state.db`, agent spawned with config.yaml + system prompt
3. **Tools loaded** via `toolsets.py` → full Hermes CLI toolset (no toolsets disabled)
4. **Agent loop** — max 60 turns, 30-minute gateway timeout, 3 API retries
5. **Response delivered** back to Telegram
6. **Coordinator daemon** (PID 4651) drains queue, ingests findings, dispatches executor
7. **Cron scheduler** fires independently — 18 active jobs on varying schedules

## 7. Active Project Status (from ground-truth probe)

| Repo | Branch | Uncommitted |
|------|--------|-------------|
| signalengine | salvage/c9-c10-m7-relocate | 20 |
| prospector | launch-hardening-2026-06-18 | 6 |
| lux | main | 3 |
| popdd-py | main | 3 |
| popdd-ts | main | 1 |
| hawoks-platform | main | 41 |
| the-introduction-exchange | feat/e33-004-kycgate | 8 |
| ritualworks | port/queries-sweep | 5 |

## 8. Findings & Recommendations

### 🔴 Unloaded LaunchDaemons
`watchdog`, `rsi`, and `progress` plists exist but services show status 0 (unloaded). These are superseded by cron equivalents (health-watchdog, improvement-probe) but the plists remain on disk as dead configuration. Consider removing them or documenting the supersession.

### 🟡 Single-provider dependency
Default model is `deepseek-v4-pro` with a single fallback `minimax/MiniMax-M3`. If both are down, the agent has no further fallback. The credential pool has 7 providers — consider adding a tertiary fallback.

### 🟢 Signal engine daemon watchdog working
The watchdog script correctly guards on `signal_engine.daemon` (underscore) and the daemon is confirmed running (PID 99744). The old hyphen-based pattern bug is fixed.

### 🟡 No channel diversity
Only Telegram is connected. Gateway supports 20+ platforms — all empty.

### 🟢 State DB healthy
64 sessions, 1,557 messages, WAL at 4M (normal for active use).

## 9. Unknowns

- **Gateway crash history** — gateway.error.log size not inspected. The crash loop watchdog (`gateway_crashloop_watch.py`) exists but its recent activity is unknown.
- **Coordinator executor activity** — `COORD_AGENTIC_EXEC=1` means the caged executor can make changes. Recent executor actions are in `coordinator.log` but not audited here.
- **RSI eval corpus** — `meta/rsi_evalsets/` exists but contents not inspected.
- **War room current state** — A war room eval was running at capture time (`warroom_eval.py --mode mutate`). Status unknown.
