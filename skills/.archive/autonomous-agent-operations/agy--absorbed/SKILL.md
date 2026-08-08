---
name: agy
description: Monitor, interact with, and troubleshoot agy (Antigravity / Gemini Cloud Code) coding agent sessions — log inspection, brain state, PTY interactions, permissions model
version: 1.0.0
author: Otto (from 2026-06-20 Prospector deploy session)
platforms: [macos]
metadata:
  hermes:
    related_skills: [claude-code, otto-operating-model, pi-governance]
---

# agy — Antigravity (Gemini Cloud Code) Agent Orchestration

agy (`~/.local/bin/agy`, v1.0.10+) is Google's Gemini Cloud Code TUI coding agent. It operates via a PTY-based terminal interface with manual tool confirmations by default. This skill covers monitoring active agy sessions, checking progress, understanding the permissions model, and troubleshooting stuck sessions.

## Key File Paths

| Path | What |
|------|------|
| `~/.local/bin/agy` | CLI binary (Mach-O 64-bit) |
| `~/.gemini/antigravity-cli/settings.json` | Global settings: model, permissions allowlist, workspace access |
| `~/.gemini/antigravity-cli/brain/<conv-id>/` | Per-conversation state: artifacts, scratch files, metadata |
| `~/.gemini/antigravity-cli/log/cli-YYYYMMDD_HHMMSS.log` | Session logs (one per agy invocation) |
| `~/.gemini/antigravity-cli/conversations/` | Conversation storage |
| `~/.gemini/antigravity-cli/history.jsonl` | Full history log |

## Monitoring Active Sessions

### 1. Find running agy instances
```bash
ps aux | grep "agy" | grep -v grep
```
Look for the PID, CWD, and start time. Long-running sessions (hours+) are normal.

### 2. Check progress via log tail
```bash
tail -40 ~/.gemini/antigravity-cli/log/cli-YYYYMMDD_HHMMSS.log
```
Key log lines:
- `Surfacing tool confirmation: "Bash" at step N` — agy is waiting for user approval
- `Responding to tool confirmation: ... approved=true` — tool was approved
- `streamGenerateContent?alt=sse` — actively thinking/sending API calls
- `Model output error:` — artifact path issue (must be within brain directory)

### 3. Check conversation brain state
```bash
ls -lt ~/.gemini/antigravity-cli/brain/<conv-id>/
```
Brain directories contain `.md` files (generated artifacts), `.metadata.json` files, and a `scratch/` directory for runtime files. Sort by modification time to see recent outputs.

### 4. Check what files agy has open
```bash
lsof -p <pid> | grep -E "\.md|\.json|\.py|cwd"
```
Shows CWD, loaded files, and log output. Use to verify what agy is currently working on.

### 5. Find the conversation ID
From the log: `Streaming conversation <conv-id>` or `Forwarding user message to conversation <conv-id>`.
From `lsof`: `brain/<conv-id>/<filename>`.

## Permissions Model

### Command allowlist
agy uses a `settings.json` whitelist under `permissions.allow`. Each entry is an exact command string. Common approved commands include `git *`, `python3 script.py`, `flyctl`, etc.

### Auto-approve all: `--dangerously-skip-permissions`
agy supports the same flag as Claude Code. Use for unattended/CI runs:
```bash
agy --dangerously-skip-permissions
```
Or for one-shot print mode:
```bash
agy --print "task" --dangerously-skip-permissions
```

### `--print` mode
Non-interactive one-shot mode (like `claude -p`). Exits when done. Useful for CI/scripting. The defunct process `agy --print ... --dangerously-skip-permissions --add-dir ...` shows the full syntax.

## PTY Stuck Sessions

**Symptom:** agy is at step N with a tool confirmation, and the log shows `Surfacing tool confirmation: "Bash" at step N` but no `Responding to tool confirmation` follows.

**Cause:** agy's PTY is waiting for manual user input (approve/reject the Bash command).

**What doesn't work:** Writing to agy's PTY (`/dev/ttys00X`) from Hermes' terminal. The PTY is sandboxed and echo/write operations don't trigger the approval input loop.

**What does work:**
1. **User switches to the agy terminal** and approves manually
2. **Kill and restart** with `--dangerously-skip-permissions` (loses conversation context)
3. **Add the desired command to `settings.json` allowlist** before restarting

## Session Lifecycle

- Sessions can run **9+ hours** continuously (observed with PID 45618, ~1200 steps)
- agy survives terminal disconnects if launched in tmux
- Tool confirmations time out eventually (exact timeout TBD, >10 min observed)
- `--print` mode sessions complete and exit; the process may linger as `<defunct>` until reaped

## Common Pitfalls

### PITFALL: Multiple agy instances confuse monitoring
When there are 2+ agy PIDs, each has its own log file and brain directory. Always match PID → log file → brain directory before reporting status.

### PITFALL: Artifact path must be inside brain directory
agy rejects file writes outside `~/.gemini/antigravity-cli/brain/<conv-id>/`. If agy tries to write to `~/.hermes/scripts/` it will error: "not a valid artifact path." The fix: copy the file into the brain first, or have agy write to brain then move it post-session.

### PITFALL: agy tool confirmation times out silently
If the user doesn't notice the confirmation prompt, agy sits idle. There's no audible notification. Status updates should mention "WAITING FOR APPROVAL at step N" to alert the user.

### PITFALL: `settings.json` model name uses display names
The model field uses display names like `"Gemini 3.5 Flash (High)"` not API identifiers. Changing this requires knowing the exact display string.
