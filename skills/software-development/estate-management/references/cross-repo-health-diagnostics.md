# Cross-Repo Health Diagnostics

When asked "what is the state of our projects" or any question about project health across multiple repos, follow this diagnostic sequence:

## 1. Quick Scan (30s)

For each repo: check git activity, test suite, and venv state:

```bash
# Recent commits
cd ~/Documents/code/<repo> && git log --oneline -5 --since="2 days ago"

# Test suite (quick summary)
cd ~/Documents/code/<repo> && .venv/bin/python -m pytest -q --tb=no 2>&1 | tail -3

# Venv exists?
ls .venv/bin/python &>/dev/null && echo "venv: yes" || echo "venv: no"
```

## 2. Test Failure Diagnosis

If tests fail, classify the failure:

**FAIL type A — ProviderExhaustedError / "operator unavailable":**
The test needs a live API key that isn't set in the test environment. Check:
- `echo ${DEEPSEEK_API_KEY:+set}` / `${MINIMAX_API_KEY:+set}` / `${GEMINI_API_KEY:+set}`
- Keys may exist in `~/.hermes/.env` but not be loaded in the shell or venv
- Source the env file: `source ~/.hermes/.env`
- If key is set but test still fails: the operator's `__init__` raises `RuntimeError` if key is empty. The test may need to mock the operator chain—this is a **test design issue**, not a production bug.

**FAIL type B — ModuleNotFoundError:**
Dependencies not installed. Source the venv or run `uv sync`.

**FAIL type C — AssertionError / unexpected value:**
Real logic change. Follow `systematic-debugging` skill protocol.

## 3. Key Status Scan Pattern

When testing multi-provider systems, check ALL required keys up front:

```bash
for key in DEEPSEEK_API_KEY MINIMAX_API_KEY GEMINI_API_KEY ANTHROPIC_API_KEY; do
  val="${!key}"
  echo "$key: ${val:+set (${#val} chars)}${val:-EMPTY}"
done
```

## 4. Cross-Repo Dependency Alignment

If repos share dependencies (e.g., both use `pydantic` or `polars`), check for version mismatches. The `idle-curiosity.py` script's Module 1 does this automatically every 30m, but you can also run manually:

```bash
cd ~/Documents/code/prospector && grep -r "^[a-zA-Z]" requirements.txt 2>/dev/null | sort
cd ~/Documents/code/signalengine && grep -r "^[a-zA-Z]" requirements.txt 2>/dev/null | sort
cd ~/Documents/code/lux && grep -r "^[a-zA-Z]" requirements.txt 2>/dev/null | sort
```

## 5. Repo Activity Signal

If a repo shows recent commits (last 2 days), include the top 2-3 commit messages in the "state of projects" response. These are often the most useful signal — they tell you what's actually changing without inspecting every file.
