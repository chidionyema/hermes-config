# Factory Operations — Prospector + Signal Engine

> Reference: how the two-component factory system works and is kept running.
> Created 2026-06-18 after first production deployment.

## Architecture (the metaphor)

```
Signal Engine (market sensors)    Prospector (idea factory)
        │                               │
        │ live feed / news              │ generate 20 candidates/hr
        │ every 60s                     │ vet through 6 gates
        │                               │
        ▼                               ▼
    equity $9.9K                   16 PASS / 174 KILL / 8 DEFER
        │                               │
        └───────────► Storefront ◄──────┘
                     (the shop)
```

- **Signal Engine is the market daemon** — monitors BTC/ETH/SOL every 60s, ingests news, runs LLM sentiment, tracks equity
- **Prospector is the idea factory** — generates 20 candidates per hour, vets through full pipeline (generate → dedup → prescreen → verify → gate → score → artifacts)
- **Both feed the storefront** — Prospector produces stocked merchandise (PASS dossiers), Signal Engine provides market context

## Starting the Factory

### Signal Engine Daemon

```bash
cd ~/Documents/code/signalengine
uv run python -m signal_engine.daemon &
```

Already running: `pid 23429`, cycling every 60s, equity at $9,901.65.

Auto-restart via cron watchdog `signal-engine-daemon-watchdog` (job_id `76074b28a126`) — checks every 5 minutes, silent when alive, notifies on restart.

**Log:** `~/Documents/code/signalengine/daemon.log` — append-only, tail for live view.

**Pydantic deprecation warning:** `settings.live_feed.dict()` should be `settings.live_feed.model_dump()` — cosmetic, no functional impact.

### Prospector Generation

```bash
cd ~/Documents/code/prospector
export $(grep -v '^#' .env | sed 's/ //g' | xargs)
PYTHONPATH=. .venv/bin/python -m prospector.run generate --candidates 20
```

**Scheduled:** every hour at `:00` via cron `prospector-daily-generation` (job_id `df1c49144256`).

**Key env vars required (all 5 in `.env`):**
- `GEMINI_API_KEY` (53 chars) — primary operator
- `DEEPSEEK_API_KEY` (35 chars) — fallback
- `ANTHROPIC_API_KEY` (108 chars) — Claude operator
- `MINIMAX_API_KEY` (125 chars) — cheap generation
- `EXA_API_KEY` (36 chars, UUID) — search grounding

**Not needed:** `BRAVE_API_KEY` (graceful degradation), `MINIMAX_GROUP_ID` (graceful degradation)

### Prospector Re-vetting Stale Candidates

```bash
cd ~/Documents/code/prospector
export $(grep -v '^#' .env | sed 's/ //g' | xargs)
PYTHONPATH=. .venv/bin/python -m prospector.run vet --title "dummy" --resume
```

**Note:** `--title` is required by argparse even when `--resume` is set — use a dummy value.
**Timeout:** Each Gemini re-vet takes 60-120s (web search × LLM). 8 deferred ≈ 8-16 min. Use background.

## Diagnostics & Health

### Prospector Catalogue Health

```bash
cd ~/Documents/code/prospector
export $(grep -v '^#' .env | sed 's/ //g' | xargs)
PYTHONPATH=. .venv/bin/python -m prospector.run diagnose
```

Common alerts:
- **quality_decay** — rolling avg PASS score < 3.0 → generator needs feedback/exploration tuning
- **zero_yield** — 0 PASS across 30+ ruled in a lane → gates may be too tight or calibration off
- **dead_gate** — gates that never fire behind kill-fast (usually `legality`, `pain_reality`) — acceptable if kill-fast stops earlier

### Signal Engine Health

```bash
tail -10 ~/Documents/code/signalengine/daemon.log
# Look for: "Cycle complete" with equity, KillSwitch, and latest timestamp
```

## Test Suite

### Prospector Tests
```bash
cd ~/Documents/code/prospector
export $(grep -v '^#' .env | sed 's/ //g' | xargs)
PYTHONPATH=. .venv/bin/python -m pytest tests/ -q --tb=short
# Expected: 380 passed, 3 skipped (golden set), 0 failed
```

**Critical:** `.env` must be sourced before running tests — they read `os.environ.get("...")` directly. CI gate will fail without env load.

### Signal Engine Tests
```bash
cd ~/Documents/code/signalengine
uv run pytest -q
```

## Configuration Constants

### Prospector `config.yaml`
- `generation.candidates_per_signal: 20` — each hourly batch
- `generation.max_per_call: 10` — max ideas per LLM call
- `generation.max_rounds: 6` — batching rounds
- `operator: [gemini, gemini_cli, deepseek, minimax]` — tiered failover
- `retrieval.provider: [exa, brave, gemini_cli, claude_cli]` — grounding chain
- Active lanes: `side_hustle, smb, growth, venture`

### Signal Engine `signal_engine/config.py`
- `DaemonConfig.tick_interval_sec: 60` — default cycle interval
- `LiveFeedIngestor` — recreation when config changes
- LLM pipeline thread: 3600s poll interval (1h) for news sentiment
