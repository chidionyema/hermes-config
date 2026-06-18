---
name: project-health-audit
description: "Periodic health check across multiple projects: outdated dependencies, npm audit vulnerabilities, test coverage scan, complexity hotspots. Designed for cron jobs and scheduled maintenance — runs fully autonomously."
version: 1.1.0
author: LUX Engine
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [health-check, audit, dependencies, security, npm-audit, test-coverage, complexity, cron, maintenance]
    related_skills: [codebase-inspection, requesting-code-review]
prerequisites:
  commands: [npm, python3]
---

# Project Health Audit

Periodically scan all active projects for dependency drift, security vulnerabilities, test coverage gaps, and code complexity hotspots. Designed as a cron job — runs fully autonomously with no user interaction.

## When to Use

- Scheduled cron job (e.g., weekly `@midnight` or `@weekly`)
- Before a major upgrade cycle to understand the scope
- When onboarding to a new machine or repo — baseline scan
- User asks "how healthy is everything" across projects
- After a long period of inactivity — check what's stale

## Workflow

### Phase 1 — Discover Projects

Find all project roots with a package manager manifest (package.json, pyproject.toml, Cargo.toml, go.mod, Gemfile):

```bash
# Find JS/TS projects
find ~/code ~/Documents/code -maxdepth 3 -name "package.json" -not -path "*/node_modules/*" | while read f; do
  dir=$(dirname "$f")
  if echo "$dir" | grep -qi "backup\|copy"; then continue; fi
  deps=$(python3 -c "import json; d=json.load(open('$f')); print('yes' if d.get('dependencies') or d.get('devDependencies') or d.get('scripts') else 'no')" 2>/dev/null)
  if [ "$deps" = "yes" ]; then echo "PROJECT:$dir"; fi
done
```

**Pitfall:** Skip `node_modules`, `.git`, `backup`, `copy` directories. Only include projects with actual dependencies or scripts — bare stubs (name + version only) are not active projects.

### Phase 2 — Parallel Health Scan (per-project)

For each discovered project, run these checks via subagent delegation. Batch **up to 5 parallel subagents** per wave (30s wall-time budget each):

**Check 1 — Outdated dependencies:**
```bash
cd <project> && npm outdated --json 2>&1
```

**Check 2 — Security vulnerabilities:**
```bash
cd <project> && npm audit --json 2>&1
```
Note: If `ENOLOCK` error (no lockfile), report "No lockfile — can't audit" as a finding, not a failure. Missing lockfile is itself a health issue.

**Check 3 — Test coverage:**
```bash
# Check for test files
ls -la test/ __tests__/ *.test.* *.spec.* 2>&1
# Check test config
ls -la jest.config.* vitest.config.* playwright.config.* 2>&1
# Check for test scripts in package.json
cat package.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(json.dumps(d.get('scripts',{}),indent=2))"
```

**Check 4 — Lockfile existence:**
```bash
ls package-lock.json yarn.lock pnpm-lock.yaml 2>/dev/null || echo "NO_LOCKFILE"
```

**For Python projects** (pyproject.toml, uv-managed):
```bash
uv lock --check 2>&1
uv run ruff check . --statistics 2>&1
# Run tests (respect project conventions)
uv run pytest tests/ -x -q 2>&1 | tail -20
```

### Phase 3 — Complexity Hotspots

For the largest source-heavy projects, identify the top 10 files by line count:

```bash
find <project> -name "*.ts" -o -name "*.tsx" -o -name "*.py" -not -path "*/node_modules/*" -not -path "*/.git/*" | xargs wc -l 2>/dev/null | sort -rn | head -10
```

**Hotspot thresholds:**
| LOC Range | Alert Level |
|-----------|-------------|
| < 400 | Normal |
| 400–599 | 🟡 Watch — consider splitting if logic-heavy |
| 600–800 | 🟠 High — likely mixing concerns |
| > 800 | 🔴 Critical — needs extraction |

### Phase 4 — Compile Report

Score each project on a 4-level scale and present as a table:

| Level | Criteria |
|-------|----------|
| 🔴 **Critical** | 1+ critical CVE, 0 test files, missing lockfile |
| 🟠 **High** | Many high vulns, major deps behind, test coverage < 20% |
| 🟡 **Medium** | Some outdated deps, test coverage present but gaps |
| 🟢 **Good** | Few/minor vulns, tests passing, deps current |

**Report format:**
```
# 🩺 Project Health Report — <DATE>

## 🔴 P1 — Immediate Action Required
[project name] — [list top findings]

## 🟠 P2 — High Priority
[project name] — [list top findings]

## 🟡 P3 — Worth Addressing
[project name] — [list top findings]

## ✅ Green Projects
[project name] — [good health notes]

## 📊 Summary Table
| Project | Vulns (C/H/M) | Outdated | Tests | Lockfile | Overall |

## 🚀 Measured Recs — Top 5 Things To Do
1. [actionable item — exact command or step]
2. ...
```

## Key Signals to Report

- **Critical CVEs in `next`** — these are the most common severe finding. `next@14.x < 14.2.35` has auth bypass (CVSS 9.1). `next@15.x < 15.5.19` has RCE (CVSS 10.0). Always call out the exact fix command.
- **Missing lockfile** (`ENOLOCK`) — blocks audit entirely. This is a P2 finding on its own.
- **Zero test files** — more common than expected. Note whether test infra exists (vitest/jest installed but no tests) vs nothing at all.
- **Hanging tests** (Python) — tests that block indefinitely rather than fail. These need debugging, not exclusion.
- **Empty test stubs** — tests/ directory exists with `.spec.ts` files that have 0 tests. Note as placeholder vs abandoned.

### Phase 5 — Functional Pipeline Diagnostics (Python Projects)

For projects with a CLI entry point and a defined pipeline (like Prospector), run the full functional stack after the static checks. This answers: "does the project actually work when you run it?"

**Prerequisites:** API keys sourced into the environment. See `references/env-sourcing.md` for the general pattern, and `references/prospector-key-setup.md` for Prospector's specific key inventory and sourcing quirks.

**Step-by-step:**

```bash
# 1. Set PYTHONPATH (project uses `python -m` or flat imports)
cd <project_dir>
export PYTHONPATH=.
```

```bash
# 2. Source environment variables (see env-sourcing.md for pitfalls)
# WRONG — doesn't persist:
#   source .env 2>/dev/null && command ...
# CORRECT:
export $(grep -v '^#' .env | sed 's/ //g' | xargs) 2>/dev/null
```

```bash
# 3. Check venv exists and deps installed
ls -d .venv
test -f .venv/bin/python && .venv/bin/python -c "import prospector" 2>/dev/null || {
  .venv/bin/pip install -e . 2>/dev/null || .venv/bin/pip install -r requirements.txt
}
```

```bash
# 4. Run full test suite (parallel)
.venv/bin/python -m pytest tests/ -n 2 -q --tb=short 2>&1
```

**Key outputs to report:**
- Pass/fail count, wall time
- List ANY failures with their short traceback
- Note skipped tests and why (e.g., golden set requires `-k golden`)
- Note baseline comparison: how does this run compare to the last known value (e.g., "380 pass (same as baseline)" or "377 pass, 3 regression — check test_blue_sky.py")

**Pitfall — subshell env sourcing:** `source .env && command...` does NOT persist env vars to the test runner because `&&` and `|` create subshells. The correct one-command pattern is:
```bash
export $(grep -v '^#' .env | sed 's/ //g' | xargs) 2>/dev/null; .venv/bin/python -m pytest ...
```
Don't use `source .env` as part of a command chain — always use `export $(grep ...)` with a semicolon before the target command.

**Pitfall — Chrome.app path in `.env`:** Some `.env` files contain shell path assignments unrelated to API keys (e.g. Chrome executable paths). These produce "No such file or directory" errors when sourced but do NOT block test execution. Ignore these errors (they're from the `.env` file's other content, not from the test commands). If you see the Chrome error, continue — tests will still run.

```bash
# 5. Run golden-set discrimination (if it exists)
.venv/bin/python -m pytest tests/test_golden_set.py -q --tb=long 2>&1
```

**Pitfall — `--resume` requires dummy `--title`:** If the project has a `vet --resume` command but argparse makes `--title` required, you need to pass a dummy title:
```bash
.venv/bin/python -m prospector.run vet --title "dummy" --resume
```
The handler checks `--resume` before `--title` in code, but argparse validates `--title` at parse time regardless. This is a known CLI design issue.

```bash
# 6. Run live pipeline on a realistic candidate (use mock if live keys unavailable)
export PROSPECTOR_OPERATOR=mock 2>/dev/null  # or "gemini"/"claude" for live
.venv/bin/python -m prospector.run vet \
  --title "Test candidate" \
  --one-liner "Brief description" \
  --why-now "Why this matters now" \
  --operator $PROSPECTOR_OPERATOR \
  ${FIXTURES:+--fixtures $FIXTURES} \
  2>&1 | tail -20
```

**Output signals:**
- **PASS / KILL / DEFER** with gate name and confidence — pipeline worked
- **DEFER with "retrieval unavailable"** — API key issue (check `.env` sourcing)
- **KILL with refuted (conf > 0.3)** — healthy kill-fast, real source cited
- **Error/exception** — regression in operator chain or config

```bash
# 7. Run project diagnostic/self-watch command (if exists)
.venv/bin/python -m prospector.run diagnose 2>&1
```

**Diagnostic signals to report:**
- 🚨 `quality_decay` — rolling score of passes dropped; generator producing lower-value candidates
- 🚨 `zero_yield` — 0 PASS across ruled candidates in a lane; may be calibration regression
- ⚠️ `dead_gate` — gates that never fire; may be unreachable behind kill-fast

```bash
# 8. Run coverage (quick, serial mode, ignore test files)
.venv/bin/pip install coverage 2>&1 | tail -1
.venv/bin/python -m coverage run -m pytest tests/ -q --tb=short 2>&1 | tail -3
.venv/bin/python -m coverage report --sort=-cover 2>&1 | tail -5

# 9. Clean up coverage artifacts
rm -rf .coverage __pycache__/ coverage/
```

**Report format:**
```
## 🔬 Functional Pipeline Diagnostics

### Test Suite: X passed, Y skipped, Z failed (Δ from baseline)
Golden set: ✅ / ❌

### Live Run: {PASS/KILL/DEFER} at gate {name} (conf {n})
E2E pipeline: ✅ / ❌

### Diagnostics: {n} alerts
  🚨 quality_decay — ...
  ⚠️ dead_gate — ...

### Coverage: {n}% overall ({n} stmts)
  Strengths: {high-coverage modules}
  Gaps: {low-coverage modules}
```

### Phase 6 — Catalogue / Store Health (if applicable)

For projects with a local store (catalogue of results), report inventory metrics:

```bash
# Counts by decision
ls store/dossiers/*.json 2>/dev/null | wc -l
ls store/listings/*.json 2>/dev/null | wc -l
ls store/kills/*.json 2>/dev/null | wc -l

# Or use project's own report command
.venv/bin/python -m prospector.run report 2>&1 | head -30
```

## Pitfalls

1. **`npm outdated --json` outputs `{}` when current** — not an error. Empty object means all deps within range.
2. **`npm audit` on fresh installs** — needs a lockfile. If missing, audit is blocked. Report as issue.
3. **Mixed-language monorepos** — a repo may have both `package.json` and `pyproject.toml`. Scan both. The `package.json` may be vestigial (zero npm deps); detect this and note it.
4. **`execute_code` blocked on cron** — cron contexts block `execute_code` (BLOCKED error). Convert all execution to `terminal()` calls or `delegate_task`.
5. **Subagent summaries are self-reported** — verify critical findings yourself. If a subagent says "test passed", re-check by running the test yourself on any project flagged as green.
6. **Module count explosion** — some scans show 1200+ transitive deps (Expo/React Native). Don't include the full tree in report — summarize the relevant direct deps.
7. **Same project in multiple paths** — e.g., `~/code/my-ebook-store` and `~/Documents/code/ebookStore/my-ebook-store`. Deduplicate by checking identical package.json structure. Note the duplication.
8. **Parallel subagent timeout** — use 30s wall-time budget per subagent for npm outdated/audit. For UV-managed Python projects, allow 60s (install/compile steps). Staged dispatch in waves of 5 to stay interruptible.

## References

- `references/cve-nextjs-common.md` — common Next.js CVEs by version range and exact fix commands
- `references/python-project-checks.md` — uv-based checks for signalengine and similar projects
- `references/env-sourcing.md` — correct `.env` sourcing pattern; subshell trap; Python loader fallback; per-project key requirements
- `references/launch-status-report.md` — P0 blocker tracking format for Prospector go-live (automated via launch-report.sh cron)
- `references/git-hygiene.md` — git backup status, stale pushes, agent-junk cleanup checks

## Companion Infrastructure

A continuous monitoring stack (`~/.hermes/scripts/repo-health-check.py`) runs alongside this skill. It checks the same repos every 2 hours via cron, detects state changes (pass→fail, new dirty files), and pushes results to Telegram only on change. Unlike this skill (one-off report), the monitoring stack tracks trends over time. See `task-resilience` skill's `references/self-monitoring-infrastructure.md` for the full architecture.

## Prospector Pipeline Operations

When running functional diagnostics on Prospector, the following patterns apply:

### Loading API Keys

Prospector reads 7 env vars at operator init. They live in its local `.env` file. The subshell trap applies — do NOT use `source .env && .venv/bin/python ...`:

```bash
export $(grep -v '^#' .env | sed 's/ //g' | xargs) 2>/dev/null
PYTHONPATH=. .venv/bin/python -m pytest tests/ -n 2 -q --tb=short
```

### Full Test Suite

```bash
cd ~/Documents/code/prospector
export $(grep -v '^#' .env | sed 's/ //g' | xargs) 2>/dev/null
PYTHONPATH=. .venv/bin/python -m pytest tests/ -q --tb=short
# Baseline: 380 pass, 3 skip (golden set), 0 fail, ~36s
```

### Golden Set

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_golden_set.py -v --tb=long
```

### Running a Real Vet (Live)

```bash
PYTHONPATH=. .venv/bin/python -m prospector.run vet \
  --title "Idea title" \
  --one-liner "Brief" \
  --why-now "Rationale" \
  --operator gemini
```

### Re-Vetting Deferred Candidates

The `--resume` flag requires a dummy `--title` due to argparse validation ordering:

```bash
PYTHONPATH=. .venv/bin/python -m prospector.run vet --title "dummy" --resume
```

### Generating Candidates

Default is 5/config. Override:
```bash
PYTHONPATH=. .venv/bin/python -m prospector.run generate --candidates 20
```

### Diagnostics

```bash
PYTHONPATH=. .venv/bin/python -m prospector.run diagnose  # alerts: quality_decay, zero_yield, dead_gate
PYTHONPATH=. .venv/bin/python -m prospector.run report     # catalogue: PASS/KILL/DEFER counts
```

### Key Metrics

- **380 tests pass, 0 fail** (baseline, updated 2026-06-18)
- **16 PASS, 174 KILL, 8 DEFER** in catalogue
- **Coverage: 68%** (gaps in operator.py 40%, retrieval.py 38%, run.py 30%)
- **68% coverage** (strengths: 36 test files at 100%; gaps: operator/retrieval/run.py need end-to-end coverage)
- **Cron:** hourly at `:00`, 20 candidates/run, deliver to origin

## Signal Engine Daemon Operations

The Signal Engine runs as a persistent daemon with a 60s tick cycle. It polls live market data, runs LLM sentiment analysis, ticks forward strategies, and monitors health.

### Starting the Daemon

```bash
cd ~/Documents/code/signalengine
uv run python -m signal_engine.daemon &
```

This must run as a **background terminal process** (not a subagent). The daemon has a `while True` loop; use `background=true` with `notify_on_complete` in Hermes.

### Verification

Check the log:
```bash
tail -5 ~/Documents/code/signalengine/daemon.log
```
Expected output shows:
```
Cycle complete. Equity: $9xxx.xx  Orders: N  KillSwitch: False
```

Process check:
```bash
ps aux | grep 'python.*signal_engine.daemon' | grep -v grep
```

### Watchdog Pattern

Since the daemon is a long-lived process that can crash, pair it with a cron watchdog that checks every 5 minutes and restarts silently:

```bash
*/5 * * * *  # cron schedule
# Script checks: pgrep -f "signal_engine.daemon"
# If dead: restart + notify
# If alive: produce no output (silent)
```

### Signal Engine Daemon Health Check

The daemon monitor (`~/.hermes/scripts/signal-engine-daemon-check.sh` or cron job) should:
1. Check process existence with `pgrep -f "signal_engine.daemon"`
2. If alive → produce no output (silent)
3. If dead → restart with `uv run python -m signal_engine.daemon &`, deliver restart message
4. Check `daemon.log` for recent "Cycle complete" entries as a secondary health signal

### Key Metrics

- **Tick interval:** 60 seconds (configurable via `daemon.tick_interval_sec`)
- **Equity:** ~$9,900 on BTC/ETH/SOL (as of 2026-06-18)
- **LLM pipeline:** runs in background thread on 1h poll for news sentiment
- **Strategies:** BTC/USDT, ETH/USDT, SOL/USDT (configurable universe)
