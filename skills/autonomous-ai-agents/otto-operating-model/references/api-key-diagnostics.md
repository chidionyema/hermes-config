# API Key Diagnostics — Finding and Fixing Missing Keys

When terminal, cron, or Python tests fail with `RuntimeError("X_API_KEY not set")` or `ProviderExhaustedError("All operators unavailable")`, the root cause is almost always: **keys exist somewhere but aren't loaded in the Hermes runtime environment.**

## Diagnostic Sequence

### Step 1 — Identify which key is missing
The error message tells you exactly which key. Prospector operators read these env vars:
- `GEMINI_API_KEY` — GeminiOperator, GeminiSearchProvider
- `DEEPSEEK_API_KEY` — DeepSeekOperator, DeepSeekSearchProvider
- `ANTHROPIC_API_KEY` — ClaudeOperator
- `MINIMAX_API_KEY` — MiniMaxOperator, MiniMaxSearchProvider
- `MINIMAX_GROUP_ID` — MiniMaxSearchProvider (optional group ID)
- `EXA_API_KEY` — ExaSearchProvider
- `BRAVE_API_KEY` — BraveSearchProvider (not always needed)
- `OPENROUTER_API_KEY` — OpenRouterSearchProvider

### Step 2 — Check the secrets file
```bash
grep -E "(GEMINI|DEEPSEEK|ANTHROPIC|MINIMAX|EXA|BRAVE|OPENROUTER)_API_KEY" ~/.config/llm/secrets.sh
```
If a key shows here, it's in the right place for interactive shells but NOT for Hermes runtime.

### Step 3 — Check .env for runtime visibility
```bash
grep -E "(GEMINI|DEEPSEEK|ANTHROPIC|MINIMAX|EXA|BRAVE|OPENROUTER)_API_KEY" ~/.hermes/.env
```
If a key is in secrets.sh but NOT in .env, Hermes cron jobs and terminal sessions won't see it.

### Step 4 — Check .zshrc for source
```bash
grep -n 'secrets.sh' ~/.zshrc
```
Line 54 of `.zshrc` sources `~/.config/llm/secrets.sh` — but ONLY for interactive shells.

### Step 5 — Verify key length
```bash
source ~/.config/llm/secrets.sh && python3 -c "
import os
for k in ['GEMINI_API_KEY','DEEPSEEK_API_KEY','ANTHROPIC_API_KEY','MINIMAX_API_KEY','EXA_API_KEY']:
    v = os.environ.get(k, '')
    print(f'{k}: {\"✅\" if v else \"❌\"} len={len(v)}')
"
```

## The Fix

Add missing keys to `~/.hermes/.env` in `KEY=VALUE` format. Do NOT use `export` — Hermes reads the file directly, not as a shell script.

```bash
source ~/.config/llm/secrets.sh
source ~/.hermes/.env 2>/dev/null

# Check which keys are now loaded
for k in GEMINI_API_KEY DEEPSEEK_API_KEY ANTHROPIC_API_KEY MINIMAX_API_KEY EXA_API_KEY BRAVE_API_KEY; do
    echo "$k={${!k}:+set (len=${#!k})}"
done
```

## Common Failure Modes

| Error | Likely Cause | Fix |
|---|---|---|
| `RuntimeError("MINIMAX_API_KEY not set")` | Key in secrets.sh, not in .env | Add to `.env` |
| `ProviderExhaustedError("All operators unavailable")` | Neither key exists (e.g., MiniMax key never created) | Create key + add to both |
| `RuntimeError("ANTHROPIC_API_KEY not set")` | Key in secrets.sh, not in .env | Add to `.env` |
| Python test works in terminal but fails in cron | `.zshrc` not sourced by cron | Keys must be in `.env` |
| Script works when run manually but fails from `delegate_task` | Subagent gets clean environment | Subagent inherits parent env — if parent doesn't have keys, child doesn't either |

## Prospector's Key Status (as of 2026-06-18)

All 5 essential keys added to `~/.hermes/.env`:
- `GEMINI_API_KEY` — 53 chars ✅
- `DEEPSEEK_API_KEY` — 35 chars ✅
- `ANTHROPIC_API_KEY` — 108 chars ✅
- `MINIMAX_API_KEY` — 125 chars ✅
- `EXA_API_KEY` — 36 chars ✅ (UUID format)
- `BRAVE_API_KEY` — Not needed per user
