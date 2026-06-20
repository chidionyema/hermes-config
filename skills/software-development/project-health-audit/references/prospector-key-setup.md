# Prospector API Key Setup

## Key Inventory

Prospector reads 7 env vars directly from the OS environment:

| Key | Status | Format | Required for |
|-----|--------|--------|-------------|
| `GEMINI_API_KEY` | ✅ Present | Key string | GeminiOperator (default moat brain), GeminiRetrievalProvider |
| `DEEPSEEK_API_KEY` | ✅ Present | Key string | DeepSeekOperator (generation tier), DeepSeekSearchProvider |
| `ANTHROPIC_API_KEY` | ✅ Present | Key string (sk-ant-...) | ClaudeOperator (optional moat fallback) |
| `MINIMAX_API_KEY` | ✅ Present | 125-char key | MiniMaxOperator (generation tier), MiniMaxSearchProvider |
| `EXA_API_KEY` | ✅ Present | 36-char UUID | ExaSearchProvider (fastest grounding — first in chain) |
| `BRAVE_API_KEY` | ❌ Missing | — | BraveSearchProvider (second in chain — gracefully degrades) |
| `MINIMAX_GROUP_ID` | ❌ Missing | — | MiniMaxSearchProvider (degraded) |

## Where Keys Live

Prospector stores its keys in **`prospector/.env`** (gitignored). This is an `export KEY=value` format file. There is also a `~/.hermes/.env` that contains the same keys for Hermes' own provider routing.

**Critical distinction:** `.env` is NOT automatically loaded by Prospector or pytest. It must be sourced into the environment before any run. Prospector reads `os.environ.get("KEY")` directly — no `.env` loader.

## Correct Sourcing Pattern

```bash
# Source ALL env vars from .env into the current shell
export $(grep -v '^#' .env | sed 's/ //g' | xargs) 2>/dev/null

# Then run Prospector
PYTHONPATH=. .venv/bin/python -m prospector.run vet --title "..." --one-liner "..." --why-now "..."
```

**Pitfall — subshell trap:** `source .env && command...` does NOT persist env vars across `&&` boundaries. Use `export $(grep ...)` with a semicolon, or chain in a single shell invocation:

```bash
# WRONG — subshell loses the env
cd ~/prospector && source .env && python -m pytest tests/

# CORRECT — exports persist
cd ~/prospector && export $(grep -v '^#' .env | sed 's/ //g' | xargs) 2>/dev/null; python -m pytest tests/
```

## Test Dependencies

The test suite (380 tests) uses `pytest-xdist` for parallel runs. Install with:
```bash
.venv/bin/pip install pytest-xdist pytest-timeout
```

Golden set (1 test) requires live API keys:
```bash
pytest tests/test_golden_set.py -k golden
```

## Cron Job

A scheduled generation job runs at 7am daily (job id: `df1c49144256`). It:
1. Changes to prospector directory
2. Sources `.env` via the export pattern
3. Runs `prospector generate --candidates 20`
4. Reports PASS/KILL/DEFER counts

The cron job uses `workdir=/Users/chidionyema/Documents/code/prospector` and has its own prompt that handles env sourcing. The job delivers results back to the same chat.
