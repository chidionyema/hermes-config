---
name: project-health-audit
description: "Periodic health check across multiple projects: outdated dependencies, npm audit vulnerabilities, test coverage scan, complexity hotspots. Designed for cron jobs and scheduled maintenance — runs fully autonomously."
version: 1.0.0
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
- `references/launch-status-report.md` — P0 blocker tracking format for Prospector go-live (automated via launch-report.sh cron)
