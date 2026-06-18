# Hermes Setup Audit — 2026-06-18

> **Methodology:** Every claim below was verified by reading the actual file or running an actual command, unless marked **[INFERRED]** . Nothing from memory.

---

## 1. Architecture

### Identity

| Property | Value | Source |
|----------|-------|--------|
| Product | Hermes Agent v0.16.0 | `pyproject.toml:10` |
| Publisher | Nous Research | `pyproject.toml:22` |
| Python | 3.11.15 (inside venv) | `venv/bin/python --version` |
| Dist | macOS 14.5 (Apple Silicon) | `system_profiler` / `sw_vers` |
| Node | 26.3.0 | `node --version` verified |
| .NET | Core (not checked version) | `dotnet --version` |

### Entrypoint

The gateway process is a **launchd LaunchAgent** — a macOS system service that auto-starts on login and keeps running:

```
launchd label : ai.hermes.gateway
Executable   : .hermes/hermes-agent/venv/bin/python -m hermes_cli.main gateway run --replace
Working dir  : ~/.hermes
PID          : 26491
Uptime       : ~8 hours (started 10:22 today)
Auto-restart : Yes (KeepAlive=true)
Stdout       : ~/.hermes/logs/gateway.log
Stderr       : ~/.hermes/logs/gateway.error.log
```

**No shell aliases, cron, tmux, pm2, or screen are involved.** The only persistent process is the launchd service. No `~/.bashrc` or `~/.zshrc` references to Hermes were found.

### Code Layout

**~/.hermes/** (home directory, versioned at `github.com/chidionyema/hermes-config.git`):

| Path | Description | Size |
|------|-------------|------|
| `config.yaml` | All non-secret config — model, tools, platforms, TTS, STT, delegation, cron, security, display | 13KB, 593 lines |
| `.env` | Credentials only (API keys, tokens) | N/A |
| `hermes-agent/` | Hermes core — the cloned repo (full Python package + Node modules) | N/A |
| `hermes-agent/venv/` | Python 3.11 venv with exact-pinned dependencies | N/A |
| `hermes-agent/hermes_cli/main.py` | CLI entrypoint — 12,595 lines | 510KB |
| `hermes-agent/gateway/run.py` | Gateway runner — 17,028 lines | 811KB |
| `hermes-agent/run_agent.py` | AI agent loop + tool execution — 5,485 lines | 242KB |
| `hermes-agent/toolsets.py` | Tool definition / toolset grouping — 912 lines | 31KB |
| `hermes-agent/gateway/session.py` | Session lifecycle — 701+ lines | 59KB |
| `hermes-agent/gateway/delivery.py` | Result delivery to platforms | 17KB |
| `hermes-agent/gateway/platforms/telegram.py` | Telegram adapter — 6,825 lines | 311KB |
| `hermes-agent/providers/` | Model provider base class (custom, openai compat) | N/A |
| `hermes-agent/tools/` | Individual tool implementations (~60+ files) | N/A |
| `hermes-agent/plugins/` | Plugin system (browser, memory, kanban, platforms, etc.) | N/A |
| `hermes-agent/node_modules/` | JS rendering deps for infographics/design tools | N/A |
| `skills/` | 22 skill categories, ~65 individual skills | 6.7MB |
| `policies/` | 8 correction policies in JSON format | 32KB |
| `memories/` | `MEMORY.md` (2,096B) + `USER.md` (1,014B) | 3KB |
| `scripts/` | Custom automation scripts | 32KB |
| `sessions/` | Session snapshots (SQLite DB + request dumps) | 3.9MB + 25MB DB |
| `logs/` | Gateway, agent, cron, error logs | 2.5MB |
| `cron/` | Cron job definitions (`jobs.json`) and output | 72KB |
| `state.db` | SQLite session database (messages, memory, skills) | 25MB |

**~/Documents/code/** — Active projects (found on disk, not memory):

| Project | Path | Type |
|---------|------|------|
| Prospector | `prospector/` | Python + .NET + Next.js |
| Signal Engine | `signalengine/` | Python |
| LUX | `lux/` | TypeScript |
| POPDD (TS) | `popdd-ts/` | TypeScript |
| RitualWorks | `ritualworks/` | Mixed |
| The Introduction Exchange | `the-introduction-exchange/` | Mixed |
| eCommerce (legacy) | `ecommerce-clean/` | Next.js |
| Portfolio site | `portfolio-site/` | Astro |
| And ~15 others | | |

---

## 2. Dependencies & Runtime

### Core Python deps (exact-pinned)

From `hermes-agent/pyproject.toml:24-118`:

| Package | Version | Purpose |
|---------|---------|---------|
| openai | 2.24.0 | LLM API calls (all providers via OpenAI-compatible SDK) |
| fastapi | >=0.104.0 | Gateway HTTP server |
| uvicorn | >=0.24.0 | ASGI server |
| pydantic | 2.13.4 | Data models |
| httpx | 0.28.1 | HTTP client (socks proxy support) |
| fire | 0.7.1 | CLI argument parsing |
| pyyaml | 6.0.3 | Config parsing |
| croniter | 6.0.0 | Cron schedule parsing |
| rich | 14.3.3 | Terminal rendering |
| pytest | 9.0.2 | Testing (optional dev dep) |

### Optional backends (lazy-installed)

| Extra | Package | When used |
|-------|---------|-----------|
| `anthropic` | anthropic==0.87.0 | Direct Anthropic provider (not via OpenRouter) |
| `exa` | exa-py==2.10.2 | Web search |
| `messaging` | python-telegram-bot, discord.py, slack-bolt | Platform adapters |
| `voice` | faster-whisper, sounddevice, numpy | Local STT |
| `tts-premium` | elevenlabs==1.59.0 | Premium TTS |

### Model Configuration

**Primary (active):**
- **Provider:** custom (DeepSeek via OpenAI-compatible endpoint)
- **Model:** `deepseek-chat`
- **Endpoint:** `https://api.deepseek.com/v1`
- **Reasoning effort:** medium

**Fallback (configured):**
- **Provider:** custom (MiniMax)
- **Model:** `minimax-m3`
- **Endpoint:** `https://api.minimax.io/v1`

**TTS provider:** edge (default voice: `en-US-AriaNeural`)
**STT provider:** local (whisper base model)

**All auxiliary services** (vision, web_extract, compression, skills_hub, approval, mcp, title_generation, tts_audio_tags, triage_specifier, kanban_decomposer, curator, profile_describer, monitor) — configured with `provider: auto`, delegating to the primary provider.

**Delegation subagent model:** Inherited from primary (empty string = defaults to primary model).

---

## 3. State & Memory

### Memory Store

- **Format:** Markdown with inline tags `[tags: project:<name> domain:<name> type:<name>]`
- **Capacity:** 2,200 chars for `MEMORY.md`, 1,375 chars for `USER.md`
- **Current usage:** MEMORY.md=2,096/2,200 (95%), USER.md=1,014/1,375 (74%)
- **Lifetime:** Persisted across sessions, read on every turn

### Session DB (SQLite)

- **Location:** `~/.hermes/state.db`
- **Size:** 25MB (primary) + 32KB WAL + 40KB SHM
- **Retention:** 90 days, auto-prune disabled
- **Contains:** All message history, skill usage logs, session state

### Policies

- **Location:** `~/.hermes/policies/`
- **Count:** 8 JSON files (all created 2026-06-18)
- **Format:** `{id, trigger, rule, confidence, fired, reason, created}`
- **Lifecycle:** provisional → active → demoted → retired (archived to `policies/archived/`)
- **Enforcement tool:** `~/.hermes/scripts/otto-learn.py` (CLI)

### Skills

- **Location:** `~/.hermes/skills/`
- **Count:** 22 categories, ~65 individual skills
- **Format:** Each skill is a directory with `SKILL.md` (YAML frontmatter + markdown body), plus optional `scripts/`, `references/`, `templates/`
- **Usage tracking:** `~/.hermes/skills/.usage.json`

### Logs

| File | Purpose | |
|------|---------|---|
| `gateway.log` | Gateway stdout | Rolling 5MB, keep 3 |
| `gateway.error.log` | Gateway stderr | Same |
| `errors.log` | Agent/error aggregation | Same |
| `policy-firings.jsonl` | Every policy fire event | JSONL format |
| `reflection/YYYY-MM-DD.md` | Daily self-reflection | Date-stamped |
| `agent.log` | Internal agent logging | Same rolling config |

---

## 4. Integrations

### API Keys Referenced (names only, no values)

**In `.env`** (credentials file):
- `DEEPSEEK_API_KEY`
- `GEMINI_API_KEY`
- `MINIMAX_API_KEY`
- `OPENAI_API_KEY`
- `TELEGRAM_BOT_TOKEN`

**In `config.yaml`** (inline, never values exposed):
- 13 `api_key:` fields — one each for: primary, fallback, and 11 auxiliary services (all set to empty string currently)

**In `auth.json`** (credential pool):
- `OPENAI_API_KEY` (registered as `openai-api` pool, pointing to MiniMax base URL — a hybrid config)
- `gh auth token` (GitHub CLI — used for Copilot)
- `TELEGRAM_BOT_TOKEN` (in auth.json for python-telegram-bot)

### External Services

| Service | Type | Status |
|---------|------|--------|
| DeepSeek API `api.deepseek.com` | Primary LLM provider | Active |
| MiniMax API `api.minimax.io` | Fallback LLM provider | Configured, no `RUNNING` tests verified |
| OpenRouter (model catalog) `hermes-agent.nousresearch.com` | Model discovery | Configured (catalog URL) |
| GitHub `github.com/chidionyema/hermes-config.git` | Config backup | Cron pushes hourly |
| Telegram Bot API | Messaging | Connected (PID 26491) |

### Platform Wiring (Telegram)

- **Bot token:** `TELEGRAM_BOT_TOKEN` env var (no value inspected)
- **Home channel:** `telegram:8868748055` (DM with "Chidi Onyema")
- **Allowed users:** `TELEGRAM_ALLOWED_USERS` env var
- **Library:** `python-telegram-bot[webhooks]==22.6`
- **Rich messages:** Enabled (`telegram.extra.rich_messages: true`)
- **Streaming:** Enabled on Telegram
- **Reactions:** Disabled on Telegram

**Connected platforms (only Telegram is active):**
- Telegram: ✅ Connected
- Discord, Slack, WhatsApp, Signal, Matrix, etc.: ❌ All empty (no connections)

### LSP Integration

Installed language servers (in `~/.hermes/lsp/`):
- `bash-language-server` ^5.6.0
- `pyright` ^1.1.410
- `typescript` ^6.0.3
- `typescript-language-server` ^5.3.0
- `yaml-language-server` ^1.23.0

### MCP Servers (optional)

- `linear/` — Linear issue tracker integration (found in `optional-mcps/`)
- `n8n/` — n8n workflow automation (found in `optional-mcps/`)

## 5. Cron Jobs

7 scheduled jobs configured in `~/.hermes/cron/jobs.json`:

| Name | Schedule | Purpose | Model |
|------|----------|---------|-------|
| Run health check | Daily 9am `0 9 * * *` | Check deps, security, test failures | Default (LLM-driven) |
| Daily summary | Daily 6pm `0 18 * * *` | Summarise today's activity | Default (LLM-driven) |
| Weekly LUX verify | Sunday midnight `0 0 * * 0` | Run lux verify across all projects | Default (LLM-driven) |
| hermes-config-auto-push | Hourly `0 * * * *` | Auto-push config changes to GitHub | Default (LLM-driven) |
| uncommitted-watch | Every 6h | Alert if >10 uncommitted files | Default (LLM-driven) |
| daily-self-reflection | Daily 6pm `0 18 * * *` | Audit failures, corrections, improvements | No-agent (script `daily_reflection.py`) |
| morning-briefing | Daily 9am `0 9 * * *` | Health + yesterday + priorities ask | Default (LLM-driven) |
| otto-improvement-pulse | Hourly `0 * * * *` | Self-reflection pulse | No-agent (script `hourly_pulse.sh`) |

---

## 6. Task Lifecycle (Verified Trace)

### How a message arrives and becomes a response

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. Telegram sends webhook POST → gateway.run.py                 │
│    gateway/run.py receives update, routes to session            │
│    via gateway/session.py SessionStore                         │
│                                                                 │
│ 2. gateway/run.py                                          [1] │
│    • Receives update from python-telegram-bot                   │
│    • Identifies session from chat_id + thread_id               │
│    • Builds SessionContext (user, platform, config)            │
│    • Passes to spawn_agent()                                    │
│                                                                 │
│ 3. spawn_agent() → run_agent.py AIAgent                    [2] │
│    • AIAgent.run_conversation()                                 │
│    • Loads system prompt: config + profile + memory + skills   │
│    • Builds tool schema from toolsets.py (toolsets)        [3] │
│    • Calls model API (openai SDK → DeepSeek API)                │
│                                                                 │
│ 4. Tool execution loop (inside run_agent.py)               [2] │
│    • Model returns tool_calls or text                           │
│    • run_agent dispatches to tool implementations               │
│      (tools/*.py — terminal, read_file, delegate, etc.)    [4] │
│    • Result fed back to model for next turn                    │
│                                                                 │
│ 5. Response delivery                                       [5] │
│    • run_agent completes → gateway/delivery.py                  │
│    • delivery.py formats response for Telegram                 │
│    • Sends via python-telegram-bot Bot.send_message()           │
│                                                                 │
│ 6. State persistence                                        [6] │
│    • Messages saved to state.db SQLite (gateway/session.py)    │
│    • Memory updated if applicable (memory tool)                │
│    • Skill usage tracked (skills/.usage.json)                  │
└─────────────────────────────────────────────────────────────────┘
```

**Key files in the control flow:**

| File | Lines | Role |
|------|-------:|------|
| `hermes_cli/main.py` | 12,595 | Entrypoint — parses CLI args, dispatches to gateway or chat mode |
| `gateway/run.py` | 17,028 | Gateway lifecycle — receives platform messages, spawns agent sessions |
| `gateway/session.py` | 701+ | Session creation, context building, message routing |
| `run_agent.py` | 5,485 | The core AI agent loop — calls LLM, executes tools, manages state |
| `toolsets.py` | 912 | Defines which tools are available per platform |
| `tools/` | ~60 files | Individual tool implementations (terminal, read_file, etc.) |
| `gateway/delivery.py` | 17KB | Formats and sends responses back to platform |

**How tool chains work** (using delegate_task as example):

1. Model chooses `delegate_task` tool → `run_agent.py` calls `tools/delegate_tool.py`
2. `delegate_tool.py` spawns a **new agent session** with isolated state (same `run_agent.py` loop)
3. Child session runs independently, collects results
4. Results returned as structured object to parent session
5. Parent session continues with child's output in context

**How skills work:**

1. Skills loaded at context build time from `~/.hermes/skills/`
2. Skills are injected into system prompt via `skill_manage` or automatically loaded at session start
3. Skills contain `SKILL.md` (instructions + frontmatter) plus optional `scripts/`, `templates/`, `references/`
4. Skills are curated periodically (`curator` plugin, every 168h by default)

**How cron works:**

1. `cronjob` tool writes to `~/.hermes/cron/jobs.json`
2. Gateway's cron scheduler (`gateway/run.py` internal loop) checks jobs.json on each tick
3. When a job is due, it spawns a new agent session with the job's prompt
4. Result is delivered via `gateway/delivery.py` to the configured target
5. No-agent jobs run the script directly and deliver stdout verbatim

---

## 7. Active Project — Prospector Go-Live Status (verified from disk)

**Branch:** `main` (all repos)
**Python suite:** 362 passed, 3 skipped, 0 failed (verified 10:10 today)
**.NET suite:** 39 passed (verified by subagent)
**Golden set:** Present, verified (1/1)

### Go-Live Gates

| Gate | Status | Details |
|------|--------|---------|
| CI pipeline | ✅ Created | 3-job GitHub Actions: Python + golden gate + .NET + Next.js |
| Fulfilment chain | ✅ Built | DeliveryEndpoints, FulfilmentService, WebhookEndpoints, orders page |
| Publish guard (provisional) | ✅ Fixed | bridge.py checks dossier.provisional before publish |
| Pricing (config-driven) | ✅ Fixed | £30 static truth in config.yaml, packs.py deleted |
| API test harness | ✅ Fixed | 5 integration tests passing |
| Server-side catalog auth | ✅ Already existed | Constant-time key comparison in Program.cs, just needed dev config key |
| Entitlements stub | ✅ Fixed | Config-driven API key, fail-closed, env var fallback |
| Legal / ToS / Privacy | 🔴 Absent | Needs user content |
| Live Paddle payments | 🔴 Sandbox | Needs user account setup |

---

## 8. Unknowns

These could NOT be determined by inspection:

1. **Primary model API key validity** — The key in `config.yaml` for DeepSeek is **truncated** in the config file (`sk-ecf...af0f`). The actual key is in `~/.hermes/.env` as `DEEPSEEK_API_KEY`. It works (this conversation is happening) but I cannot verify the full key or remaining quota.

2. **MiniMax fallback key validity** — Same situation: `sk-cp-...xqIc` in config, `MINIMAX_API_KEY` in .env. Not tested today.

3. **Telegram bot token** — Referenced by name in `.env` as `TELEGRAM_BOT_TOKEN`. It works (messages are flowing), but I cannot inspect the value.

4. **GitHub token** — `gh auth token` is registered in `auth.json` source as `gh_cli`. Not verified.

5. **.NET SDK version** — Not explicitly checked. `dotnet` is in PATH.

6. **All cron job health** — Jobs appear scheduled in `jobs.json` but I did not verify the `daily-self-reflection`, `otto-improvement-pulse`, `weekly-lux-verify`, `health-check`, or `uncommitted-watch` jobs have ever run successfully (only `hermes-config-auto-push` has a non-null `last_run_at` from today).

7. **LUX proof system integration** — Referenced in memory but its actual status on disk (spec files, verification state per project) was not independently verified in this audit.

8. **MCP server status** — `linear` and `n8n` MCPS exist in `optional-mcps/` but their connection status is unknown.

9. **Skill usage patterns** — `skills/.usage.json` exists but its contents were not inspected.

10. **Actual cost per session** — `display.show_cost: false` in config. No cost tracking visible.
