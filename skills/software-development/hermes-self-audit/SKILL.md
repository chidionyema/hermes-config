---
name: hermes-self-audit
description: Generate a complete audit of the Hermes setup — architecture, config, state, integrations, and task lifecycle.
---

# Hermes Self-Audit

## Trigger
Run this when the user asks "audit your setup", "document yourself", "how are you wired", or "show your configuration". Also run after significant config changes to update the audit.

## How to run

Execute each of the following commands and compile results into a single Markdown report. Do NOT describe from memory — inspect and report only what you find.

### 1. Identity & Entrypoint

```bash
# Launchd service
launchctl list 2>/dev/null | grep -i hermes
cat ~/Library/LaunchAgents/*hermes*.plist
cat ~/Library/LaunchAgents/*ot-*.plist 2>/dev/null || echo "No otto launchd plists"

# Cron
cat ~/.hermes/cron/jobs.json | python3 -c "import json,sys; d=json.load(sys.stdin); [print(f'{j[\"id\"][:12]}: {j.get(\"name\",\"?\")} | {j[\"schedule\"][\"display\"]} | enabled={j.get(\"enabled\",\"?\")}') for j in d.get('jobs',[])]"

# Shell config
grep -i 'hermes\|otto\|gateway' ~/.zshrc ~/.bashrc ~/.aliases 2>/dev/null || echo "No shell entries found"

# Running process
ps aux | grep -E '[h]ermes|[g]ateway' | head -5
```

### 2. Code Layout

```bash
find ~/.hermes -maxdepth 2 -not -path "*/node_modules/*" -not -path "*/.git/*" -not -path "*/__pycache__/*" -not -path "*/venv/*" -not -path "*/hermes-agent/hermes_cli/*" -not -path "*/hermes-agent/agent/*" -not -path "*/hermes-agent/apps/*" -not -path "*/hermes-agent/cron/*" -not -path "*/hermes-agent/assets/*" | sort
```

### 3. Dependencies & Runtime

```bash
~/.hermes/hermes-agent/venv/bin/python --version
node --version
dotnet --version 2>/dev/null || echo ".NET not verified"

# Key deps
grep -A 100 'dependencies = \[' ~/.hermes/hermes-agent/pyproject.toml | grep -m 20 '".*"'

# .env key names
grep -o '^[A-Z_]*=' ~/.hermes/.env | sed 's/=//' | sort -u
```

### 4. State & Memory

```bash
du -sh ~/.hermes/logs/
du -sh ~/.hermes/policies/
du -sh ~/.hermes/memories/
du -sh ~/.hermes/state.db*
wc -c ~/.hermes/memories/*.md
find ~/.hermes/policies -type f | wc -l
```

### 5. Integrations

```bash
cat ~/.hermes/gateway_state.json | python3 -m json.tool
cat ~/.hermes/channel_directory.json | python3 -m json.tool
cat ~/.hermes/auth.json | python3 -c "import json,sys; d=json.load(sys.stdin); [print(f'{k}: {len(v)} entries') for k,v in d.get('credential_pool',{}).items()]"
```

### 6. Control Flow

Read these files and extract the message flow:
- `~/.hermes/hermes-agent/gateway/run.py` (first 100 lines for overview)
- `~/.hermes/hermes-agent/gateway/session.py` (class docstrings for session lifecycle)
- `~/.hermes/hermes-agent/run_agent.py` (first 50 lines for overview)
- `~/.hermes/hermes-agent/toolsets.py` (first 80 lines for tool list)

### 7. Verify all claims

Every statement should have a source file path or command output backing it.
Mark anything you **inferred** as `[INFERRED]` and anything you could NOT determine as an **Unknown**.

## 8. Operationalisation Check (Created vs. Running)

After creating any artifact (policy, script, cron, gate, tool, skill), verify it's **operational** — not just sitting on disk. The pattern that cost us 4 rounds of correction in one session is that created artifacts were never verified at creation time.

For each artifact, run the corresponding check in the **same turn**:

- **Script** → `python3 <script> --help` or run with test input
- **Cron job** → verify it appears in `jobs.json`, check `last_run_at` after next tick
- **Policy** → verify `firings_log` entry appears after a matching action
- **Dispatch gate** → `python3 dispatch_gate.py "should I do X"` → must return BLOCKED
- **Skill** → `skill_view(name)` → verify it loads without error
- **Config change** → re-read target file to verify the change persisted

When retro-auditing, for every item in the system ask: **does this have a runtime trigger, or is it just a file?** If it's just a file, it's not operational — fix that or delete it.

## Output format

Write to `~/.hermes/reports/hermes-setup-audit-YYYY-MM-DD.md` using this structure:

```markdown
# Hermes Setup Audit — YYYY-MM-DD

> Methodology: Every claim below was verified by reading the actual file or running
> an actual command, unless marked [INFERRED].

## 1. Architecture (identity, entrypoint, code layout)
## 2. Dependencies & Runtime (language, packages, model config)
## 3. State & Memory (formats, sizes, locations)
## 4. Integrations (API keys by name, external services, platform wiring)
## 5. Cron Jobs (all active jobs)
## 6. Task Lifecycle (how a message becomes a response — trace the files)
## 7. Active Project Status (verified from disk)
## 8. Unknowns (explicitly list what you could NOT determine)
```
