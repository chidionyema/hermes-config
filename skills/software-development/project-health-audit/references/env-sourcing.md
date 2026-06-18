# Environment Variable Sourcing Pitfalls

## The core problem

Python projects that read API keys from `os.environ` (via `os.environ.get("KEY_NAME")`) need those keys in the process environment before the interpreter starts. `.env` files are not automatically loaded — they're just shell-sourced files.

## The trap: shell subshells

**WRONG** — each `&&` creates a subshell; the export never reaches the Python process:
```bash
source .env && python -m pytest tests/  # KEYS NOT AVAILABLE
source .env 2>/dev/null; python ...      # Still doesn't work (; doesn't help)
```

**RIGHT** — export in the same process before the command:
```bash
export $(grep -v '^#' .env | sed 's/ //g' | xargs) 2>/dev/null
PYTHONPATH=. .venv/bin/python -m pytest tests/
```

**ALSO RIGHT** — one-liner with the export in the same shell:
```bash
export $(grep -v '^#' .env | xargs) && .venv/bin/pytest tests/ -n 2 -q
```
(Here the `&&` works because the export happens to the current shell, not a subshell.)

## Why `source .env` doesn't work in subcommands

When you write:
```bash
cd project && source .env && .venv/bin/pytest tests/
```
The `cd` is executed in a subshell from the terminal tool. The `source .env` is ALSO in that subshell. The exports created by `source .env` ARE available to `.venv/bin/pytest` — **this actually works** for a single `&&` chain.

The actual failure mode is: `source .env` itself can **fail silently** (exit non-zero) because the `.env` file contains lines that aren't valid shell syntax. Common causes:

| Cause | Example `.env` line | Error |
|-------|---------------------|-------|
| Quoted values with spaces | `CHROME_PATH="/Applications/Google Chrome.app/.../Google Chrome"` | `No such file or directory` |
| Comments after values | `AUTH=x # my key` | `AUTH=x: command not found` |
| Empty lines or comments | `# this is a comment` | (harmless) |

When `source .env` hits a line that looks like a command (e.g. a file path with a space), it tries to execute it and fails. **The entire `source` fails**, and none of the subsequent exports are available.

## The fix: grep-only approach

Skip source entirely — extract only the export-able lines:
```bash
export $(grep -v '^#' .env | grep -v '^$' | sed 's/ //g' | xargs)
```

For `.env` files with spaces in values (like Chrome paths), the grep approach also breaks. The most reliable fix is a Python loader:

```bash
cd project && python3 -c "
import os
with open('.env') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#'):
            k, _, v = line.partition('=')
            os.environ[k.strip()] = v.strip().strip(\"'\").strip('\"')
" && .venv/bin/pytest tests/ -n 2 -q
```

## Verification

After sourcing, verify key availability with:
```bash
echo "GEMINI length: ${#GEMINI_API_KEY}"
echo "DEEPSEEK length: ${#DEEPSEEK_API_KEY}"
# etc.
```
Length 0 = not sourced. Length > 0 = loaded.

## Prospector-specific

Prospector reads these env vars at operator init (raises `RuntimeError` if missing):
- `GEMINI_API_KEY` — GeminiOperator (Gemini API client)
- `DEEPSEEK_API_KEY` — DeepSeekOperator, DeepSeekSearchProvider
- `ANTHROPIC_API_KEY` — ClaudeOperator (Anthropic API)
- `MINIMAX_API_KEY` — MiniMaxOperator, MiniMaxSearchProvider
- `EXA_API_KEY` — ExaSearchProvider (primary fast grounding)
- `BRAVE_API_KEY` — BraveSearchProvider (optional secondary grounding)
- `MINIMAX_GROUP_ID` — MiniMaxSearchProvider (optional group context)

## Multi-file sourcing

When keys are split across multiple `.env` files (e.g., project-local `.env` + global `~/.hermes/.env`), source both:

```bash
export $(grep -v '^#' .env | xargs) $(grep -v '^#' ~/.hermes/.env | xargs)
```

The second one overwrites any duplicates from the first (last write wins). Keep project-specific keys in the local `.env`, shared keys in `~/.hermes/.env`.
