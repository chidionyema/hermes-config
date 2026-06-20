---
name: claude-code
description: "Continuous Claude Code consultation via persistent tmux channel (Otto's default), plus print mode and interactive PTY orchestration. Hermes stays a coordinator; Claude reasons, Hermes orchestrates."
version: 2.3.0
author: Hermes Agent + Teknium
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Coding-Agent, Claude, Anthropic, Code-Review, Refactoring, PTY, Automation]
    related_skills: [codex, hermes-agent, opencode]
---

# Claude Code — Hermes Orchestration Guide

Delegate coding tasks to [Claude Code](https://code.claude.com/docs/en/cli-reference) (Anthropic's autonomous coding agent CLI) via the Hermes terminal. Claude Code v2.x can read files, write code, run shell commands, spawn subagents, and manage git workflows autonomously.

## Prerequisites

- **Install:** `npm install -g @anthropic-ai/claude-code`
- **Auth:** run `claude` once to log in (browser OAuth for Pro/Max, or set `ANTHROPIC_API_KEY`)
- **Console auth:** `claude auth login --console` for API key billing
- **SSO auth:** `claude auth login --sso` for Enterprise
- **Check status:** `claude auth status` (JSON) or `claude auth status --text` (human-readable)
- **Health check:** `claude doctor` — checks auto-updater and installation health
- **Version check:** `claude --version` (requires v2.x+)
- **Update:** `claude update` or `claude upgrade`

## Three Orchestration Modes

Hermes interacts with Claude Code in three fundamentally different ways. Choose based on the task.

**Mode 0 (NEW, 2026-06-18) — Continuous Consult Channel** is the default for Otto's coordinator mode. See the dedicated section below. The other two are retained for non-Otto contexts.

## Mode 0: Persistent Consult Channel (Otto's default — 2026-06-18)

Otto's operating mode is **coordinator + continuous consult** (see `otto-operating-model`). Otto does NOT do the work itself — it triages, dispatches, and reports. For any non-trivial issue, the protocol is: open a persistent Claude Code tmux session, drive it with full context, fold its corrections into your own model, then surface the result.

**This replaces one-off print-mode dispatches for triage tasks.** One-shot is reserved for: scripts that must run unattended, isolated worktrees, CI-style automation, and tasks where the user explicitly said "ask Claude once and tell me."

### Launch the channel

```bash
# 1. Create a dedicated tmux session (one per issue domain)
tmux new-session -d -s otto-claude-<domain> -x 160 -y 50

# 2. Launch Claude Code with permissions bypass
tmux send-keys -t otto-claude-<domain> 'cd <project-dir>' Enter
tmux send-keys -t otto-claude-<domain> 'claude --dangerously-skip-permissions' Enter

# 3. Wait for the welcome screen, then send the framing
sleep 4
tmux send-keys -t otto-claude-<domain> Enter        # any dialog
tmux send-keys -t otto-claude-<domain> '/clear' Enter  # clean slate for the real prompt
```

### Send a real prompt

**CRITICAL pitfall (burnt 2026-06-18):** multi-line `tmux send-keys` commands break if the prompt contains `DO:`, parentheses, or other shell metacharacters — bash interprets them as separate commands BEFORE tmux forwards. The fix is to write the prompt to a file and use `load-buffer` + `paste-buffer`:

```bash
# Write the prompt to a temp file
write_file(path="/tmp/claude-prompt.txt", content="<your prompt here>")

# Load it into tmux's paste buffer
tmux load-buffer /tmp/claude-prompt.txt

# Paste it into Claude
tmux paste-buffer -t otto-claude-<domain>
sleep 1
tmux send-keys -t otto-claude-<domain> Enter
```

NEVER send a multi-line prompt via inline `tmux send-keys '...'` with newlines, parentheses, or `DO:`/`(`/`)` — they will be mangled by shell interpretation.

### Monitor and steer

```bash
# Check progress
tmux capture-pane -t otto-claude-<domain> -p -S -50

# Steer mid-conversation (send a follow-up)
write_file(path="/tmp/claude-followup.txt", content="<follow-up>")
tmux load-buffer /tmp/claude-followup.txt
tmux paste-buffer -t otto-claude-<domain>
sleep 1
tmux send-keys -t otto-claude-<domain> Enter

# Cancel mid-task (Esc Esc rewind or Ctrl+C)
tmux send-keys -t otto-claude-<domain> Escape Escape
tmux send-keys -t otto-claude-<domain> C-c
```

### CRITICAL pitfall: the `~/.local/bin/claude` symlink

**Symptom:** `claude` from PATH prints "The operation couldn't be completed. Unable to locate a Java Runtime." even though Java is installed.

**Cause (confirmed 2026-06-18):** the symlink `~/.local/bin/claude` is a Bun-bundled native installer wrapper that misidentifies itself as needing Java. The **actual Claude Code binary** is at `~/.local/share/claude/versions/<version>` (Mach-O 64-bit, NOT a Java wrapper).

**Fixes (in order of preference):**

1. **Direct invocation** — use the real binary path:
   ```bash
   ~/.local/share/claude/versions/2.1.181 --dangerously-skip-permissions
   ```
2. **Fix the symlink** — point `~/.local/bin/claude` at the real binary:
   ```bash
   rm ~/.local/bin/claude
   ln -s ~/.local/share/claude/versions/2.1.181 ~/.local/bin/claude
   ```
3. **PATH override** — prepend the versions dir:
   ```bash
   export PATH="$HOME/.local/share/claude/versions/2.1.181:$PATH"
   ```

**Verify before launching tmux:**
```bash
~/.local/bin/claude --version 2>&1    # if "Java Runtime" → symlink is broken
~/.local/share/claude/versions/2.1.181 --version 2>&1  # should print "X.X.X (Claude Code)"
```

### CRITICAL pitfall: clearing context for a real prompt

Claude Code's interactive TUI may have stale input queued from prior `send-keys` calls (the user's earlier `which claude`, `echo $PATH`, etc.). After a fresh launch, before sending your real prompt:

1. Send `Escape` (cancel any pending input)
2. Send `C-c` (interrupt current generation)
3. Send `/clear` Enter (wipe context)
4. Wait 2s
5. THEN send your real prompt via `load-buffer` + `paste-buffer`

Skipping this means your real prompt may be queued after diagnostic noise, and Claude will respond to the diagnostics first.

### CRITICAL pitfall: paste accumulation on re-prompt (burnt 2026-06-18)

**Symptom:** A second `load-buffer` + `paste-buffer` to a Claude TUI pane does NOT replace the first paste — it appends. If your first paste sat in the input box unsent (because the first Enter went to a different command, or got swallowed by a dialog), the second paste stacks on top. Result: Claude receives garbled text, two prompts concatenated, or worse, reads an unsent unsanitized draft as the user's intent.

**Fix:** before EVERY new paste into a Claude TUI pane, clear the input box first:

```bash
# 1. Cancel any pending rewind/dialog
tmux send-keys -t otto-claude-<domain> Escape

# 2. Move cursor to start of line, kill to end of line
tmux send-keys -t otto-claude-<domain> C-a
tmux send-keys -t otto-claude-<domain> C-k

# 3. Wait, then send the new prompt
sleep 1
write_file(path="/tmp/claude-prompt.txt", content="<new prompt>")
tmux load-buffer /tmp/claude-prompt.txt
tmux paste-buffer -t otto-claude-<domain>
sleep 1
tmux send-keys -t otto-claude-<domain> Enter
```

**Why `C-a C-k` and not `C-u`:** `C-u` kills from cursor to start of line but Claude's TUI may interpret it as a slash command prefix (`/`). `C-a` then `C-k` (kill to end of line) is universal and unambiguous.

### Session lifecycle

- **Keep the session alive across multiple triage rounds** — `/clear` between topics, don't `tmux kill-session` between rounds
- **One session per issue domain** — separate sessions for "signal-engine triage" vs "lux verification" vs "prospector generation"
- **Survival across Hermes restarts** — the tmux session is independent of Hermes; it persists until `tmux kill-session` or system reboot
- **Naming convention** — `otto-claude-<domain>` (e.g., `otto-claude-signal-engine`)

### Stalled Claude detection + kill-and-merge (CRITICAL, 2026-06-18)

**Symptom (cost: 4 user messages in a row — "Update?", "Why not?", "Update from Claude?", "Where's the response?"):** `tmux capture-pane -t otto-claude-<domain> -p -S -50` shows the same final lines for >5 minutes. No fresh tool calls, no new text, no `❯` prompt. The session is **stalled** — either context-window exhausted silently, model output truncated, or the TUI swallowed a prompt.

**Don't:** spin up a second Claude "to help." The user's verbatim correction: *"kill the sessions and start again with one session"*. Two stalled Claudes stitched together cost more than one fresh one.

**Do (the kill-and-merge pattern):**

```bash
# 1. Diagnose: confirm stall with two captures 30s apart
tmux capture-pane -t otto-claude-<domain> -p -S -50 > /tmp/cap1.txt
sleep 30
tmux capture-pane -t otto-claude-<domain> -p -S -50 > /tmp/cap2.txt
# diff /tmp/cap1.txt /tmp/cap2.txt — if identical or near-identical, stalled

# 2. Capture the full context that the stalled session HAD (so the fresh one inherits)
tmux capture-pane -t otto-claude-<domain> -p -S -1000 > /tmp/claude-stalled-context.txt

# 3. Kill the stalled session
tmux kill-session -t otto-claude-<domain>

# 4. Start ONE fresh session with the merged context dump
tmux new-session -d -s otto-claude-<domain> -x 160 -y 50
tmux send-keys -t otto-claude-<domain> 'cd <project-dir>' Enter
tmux send-keys -t otto-claude-<domain> '~/.local/share/claude/versions/<v> --dangerously-skip-permissions' Enter
sleep 4
tmux send-keys -t otto-claude-<domain> Enter  # trust dialog
tmux send-keys -t otto-claude-<domain> '/clear' Enter  # clean slate

# 5. Send a prompt that includes: the original brief + the stalled session's last useful output + "continue from where the previous session stalled"
write_file(path="/tmp/claude-resume.txt", content="[ORIGINAL BRIEF]

[STALLED SESSION CONTEXT - last 1000 lines]
$(cat /tmp/claude-stalled-context.txt)

Continue from where the previous session stalled. Do not restart items already completed. Pick up the in-flight item.")
tmux load-buffer /tmp/claude-resume.txt
tmux paste-buffer -t otto-claude-<domain>
sleep 1
tmux send-keys -t otto-claude-<domain> Enter
```

**Prevention:** before each `tmux capture-pane`, check the captured tail for a timestamp or new tool-call line. If the same prompt has been waiting without progress for 5+ minutes, kill-and-merge immediately — don't wait for the user to notice.

### CRITICAL pitfall: Claude at idle `❯` prompt (added 2026-06-19)

**Symptom (different from mid-execution stall):** `tmux capture-pane` shows Claude finished its turn, output the handback, and is sitting at an empty `❯` prompt — but no fresh text appears for 5+ minutes and the session hasn't auto-exited. Claude is **idle waiting for the next prompt**, NOT stalled mid-task.

**How to disambiguate from mid-execution stall:**
- Mid-execution stall: no `❯` prompt, no `●` tool call in the last 50 lines, same `⏵⏵ bypass permissions on` status bar unchanged, CPU near 0%.
- Idle at `❯` prompt: Claude wrote handback text, then `❯` appears with empty cursor, status bar shows last cooking time, CPU near 0%.

**Why kill-and-merge is wrong here:** the work is DONE. Killing the session and starting fresh loses the handback that just landed. The right move is to **read the handback, run the verification probes Otto was waiting for, and surface the receipts**.

**The right response to Claude-at-idle-prompt (the 4-probe handoff):**

```bash
# 1. Capture the handback Claude just produced
tmux capture-pane -t otto-claude-<domain> -p -S -200 > /tmp/claude-handback.txt

# 2. Inspect: is the handback complete? Does it claim "commit SHA: <sha>"? Is there an open question?
grep -E "commit SHA|❯|asked|waiting" /tmp/claude-handback.txt

# 3. If Claude said "should I commit?": that's a user-decision gate. Surface the handback
#    + your own probe receipts on the deliverable + ask the user.
# 4. If Claude reported "done" but the commit SHA is missing: Claude's handback is
#    incomplete. Either (a) send a follow-up: "commit, push if remote, then send
#    the SHA + 4 read-only probes (cron job states, orphan count, gateway status,
#    watchdog log). Format as receipt, not narrative" — OR (b) if CPU is 0 and
#    Claude appears truly dead, run the 4 probes yourself (they're read-only) and
#    bring receipts to the user.
```

**Why this matters (2026-06-19 lesson):** Claude cooked 12m, output a thorough audit, hit `❯ commit this`, then went idle. Otto kept polling the pane and asking the user "Update?" three times in a row — exactly the filler-message anti-pattern in `dropped-ball-prevention`. The fix is: **the moment you see `❯` with handback text above it, that's the receipt, not a stall. Stop polling. Surface the handback.**

**Prevention rule:** set a 60-second self-poll on the Claude session. After 60s with no new text and a `❯` visible, capture the pane once more. If the handback is there, surface it. If not, treat as mid-execution stall (use kill-and-merge above).

### CRITICAL pitfall: Claude handback MUST include commit + proof (added 2026-06-19)

**The rule (from Chidi, verbatim 2026-06-19):** "Every time you delegate to Claude, Claude must fix root cause safely and **commit** and send proof."

**Handback contract — what Claude must produce before its turn is "done":**

1. **Commit SHA** (or explicit reason no commit was made, e.g. "drift in working tree not from this fix — needs scope review")
2. **Push confirmation** if a remote exists (or explicit "no remote configured")
3. **Post-fix verification probes** (4 read-only probes minimum for cron/system work):
   - Cron job status (which jobs were failing, what's their state now)
   - Orphan process count (cron/script related, not system daemons)
   - Gateway status (running, restart loop state)
   - Watchdog log tail (alerts resolved or active)
4. **Audit report path** (e.g. `~/.hermes/reports/<topic>-<date>.md`) if the work was a structural audit

**Format as receipt, not narrative.** Each probe result should be: command run, exit code, key output line, conclusion. Tables over prose.

**Otto's verification protocol after Claude handback:** do NOT trust the handback verbatim. Run the 4 probes yourself in parallel via `terminal()`, verify the SHA exists with `git log --oneline -3`, stat the report file. If any probe contradicts Claude's handback, the handback is wrong — surface the contradiction to the user, not the handback.

**When Claude's handback is missing the commit** (the 2026-06-19 actual scenario): Claude finished the audit + wrote fixes to the working tree + prompted "❯ commit this" but did NOT commit. Otto's response was to keep polling the pane. The correct response is: (1) read the handback, (2) inspect the working tree diff (`git status --short`), (3) if the diff is exactly Claude's claimed fixes (≤N files, all in scope), commit and push yourself; (4) if the diff includes drift Claude didn't claim, **stop and ask the user** — "Claude fixed 4 files but the working tree has 24 modified + 7 untracked. Commit just the 4, or include drift?" Do NOT auto-commit drift. Scope discipline on commits is non-negotiable.

### When NOT to use Mode 0

- **One-shot CI tasks** → use Mode 1 (print mode)
- **Multi-hour batch jobs that need worktree isolation** → use Mode 2 (interactive PTY) with `--worktree --tmux`
- **Anything you must run unattended** → Mode 0 requires continuous steering; print mode does not

## Multi-Session Coordination (NEW 2026-06-18)

When you need **more than one Claude reasoning about a problem at once** — e.g., a live triage session PLUS a separate audit session watching the triage — open multiple `otto-claude-<domain>` tmux sessions and let them observe each other.

**For full recipes, failure modes, and the cross-pane observation pattern, see `references/multi-session-coordination.md`.** Key principles:

- One session per issue domain (or per role within a domain)
- Audit/triage sessions explicitly told to cross-read each other via `tmux capture-pane`
- Always target send-keys by `-t <named-session>`; never bare `tmux send-keys`
- Clear input boxes (`Escape; C-a; C-k`) on ALL sessions before any disambiguation
- Don't relay verbatim findings between sessions; Otto reformulates

The audit-prompt boilerplate that works (verbatim — adapt to your domain):

> "Every few minutes, run `tmux capture-pane -t otto-claude-<triage> -p -S -60` to see what the live triage is finding. If the triage reaches a conclusion you disagree with, raise it. If your own work is now redundant because the triage already covered it, say so and stop. DO NOT edit any files. DO NOT run the daemon. If you find a real fix that needs shipping, surface it to Otto — do not apply it."

### Pattern: live triage + meta-audit

```bash
# Session 1: live triage (does the actual reasoning)
tmux new-session -d -s otto-claude-triage -x 160 -y 50
tmux send-keys -t otto-claude-triage 'cd <project>' Enter
tmux send-keys -t otto-claude-triage '~/.local/share/claude/versions/2.1.181 --dangerously-skip-permissions' Enter
# ... (launch + clear + paste triage prompt as above)

# Session 2: meta-audit (watches the triage, audits the agent/system)
tmux new-session -d -s otto-claude-audit -x 160 -y 50
tmux send-keys -t otto-claude-audit 'cd ~' Enter
tmux send-keys -t otto-claude-audit '~/.local/share/claude/versions/2.1.181 --dangerously-skip-permissions' Enter
# ... (paste audit prompt)
```

The audit prompt should explicitly tell the auditor to read the triage session via `tmux capture-pane -t otto-claude-triage -p -S -60` — this is the **meta-supervision signal** that turns two Claudes into a closed-loop system.

### When to spin up a parallel Claude (the "who's so slow" trigger)

A single Claude session is the bottleneck when:
- The audit queue has ≥3 substantive items still queued and Claude is past the keystone
- The user says "who so slow", "send the rest to another Claude", or any parallel-velocity complaint
- The remaining items are non-overlapping (one session can take a keystone, the other can take everything else)

**The split discipline (corrected 2026-06-18):**

1. **Pre-existing session owns the keystone** — the item already in flight stays where it is. Don't yank the work.
2. **New session takes non-overlapping items** — explicitly partition the queue so neither session edits the same files. Item assignments must be in the prompt.
3. **Brief the new session with the full context dump** — what the original session is doing, what the queued items are, what NOT to duplicate, what to hand back. A new session that doesn't know the audit context will redo work.
4. **Naming** — `otto-build` for the parallel shiper, `otto-claude-<domain>` for the original. Don't reuse names.
5. **Handback protocol** — each session produces its own handback; Otto merges them in chat. Don't relay verbatim between sessions.

**The non-overlap rule (enforced by the brief):** the parallel session's brief must list which items the original session owns and forbid the parallel session from touching them. Example: "Items 2-10 are yours. Item 1 (gateway hooks) is the original session's keystone — do not start it, do not preempt it, do not duplicate it."

**Cost guard:** two parallel sessions is the max. If the queue is still >3 items after the second session finishes, fix the dependency graph (some items are blocking others), don't add a third session.

### Disambiguating sessions

When two sessions are running in parallel, a steer-into-wrong-pane mistake is expensive. Disambiguate every message you send:

```bash
# WRONG: tmux send-keys defaults to the active pane
tmux send-keys 'fix the watchdog' Enter
# ↑ Goes to whichever pane is "current" — possibly the wrong Claude

# RIGHT: always target the named session
tmux send-keys -t otto-claude-triage 'fix the watchdog only' Enter
tmux send-keys -t otto-claude-audit 'do not act on what you saw' Enter
```

When you disambiguate, **also clear the input box** (C-a C-k) on the OTHER session to prevent a queued unsent prompt from being interpreted later. A common failure mode: the user types "fix the watchdog" intending it for triage, but the cursor focus is on audit; the audit Claude sees "fix the watchdog" and starts editing watchdog scripts that the triage Claude was only inspecting.

### Steering discipline (Otto's role)

When you have two Claudes running:
- **Don't let one steer the other directly.** Triage Claude and audit Claude should each have their own context. Otto relays the meta-finding ("the audit found that the watchdog points at the wrong program") to the user, then the user decides.
- **Pass findings, not commands.** If audit Claude says "watchdog is supervising the wrong program," do NOT pipe that verbatim into triage Claude. Otto reformulates: "the audit agrees with your Q1 finding. Hold. I'm relaying both to the user."
- **Pause both before surfacing to the user.** `tmux send-keys -t <both> Escape; tmux send-keys -t <both> C-c` then report. This prevents either Claude from doing speculative work while the user thinks.
- **Otto does NOT apply jobs.json handbacks from Claude (added 2026-06-18, ball 18).** When Claude hands back a cron diff, Claude applies it itself via direct file edit or the `cronjob` tool inside its own session. Otto relays the receipt from Claude's handback, not the action. The `cronjob` tool is reserved for Otto's own new crons that aren't part of a Claude audit; using it for a Claude handback is the same self-certification anti-pattern as running probes yourself.

## Mode 1: Print Mode (`-p`) — Non-Interactive (PREFERRED for one-shot tasks)

Print mode runs a one-shot task, returns the result, and exits. No PTY needed. No interactive prompts. This is the cleanest integration path.

```
terminal(command="claude -p 'Add error handling to all API calls in src/' --allowedTools 'Read,Edit' --max-turns 10", workdir="/path/to/project", timeout=120)
```

**When to use print mode:**
- One-shot coding tasks (fix a bug, add a feature, refactor)
- CI/CD automation and scripting
- Structured data extraction with `--json-schema`
- Piped input processing (`cat file | claude -p "analyze this"`)
- Any task where you don't need multi-turn conversation

**Print mode skips ALL interactive dialogs** — no workspace trust prompt, no permission confirmations. This makes it ideal for automation.

### Mode 2: Interactive PTY via tmux — Multi-Turn Sessions

Interactive mode gives you a full conversational REPL where you can send follow-up prompts, use slash commands, and watch Claude work in real time. **Requires tmux orchestration.**

```
# Start a tmux session
terminal(command="tmux new-session -d -s claude-work -x 140 -y 40")

# Launch Claude Code inside it
terminal(command="tmux send-keys -t claude-work 'cd /path/to/project && claude' Enter")

# Wait for startup, then send your task
# (after ~3-5 seconds for the welcome screen)
terminal(command="sleep 5 && tmux send-keys -t claude-work 'Refactor the auth module to use JWT tokens' Enter")

# Monitor progress by capturing the pane
terminal(command="sleep 15 && tmux capture-pane -t claude-work -p -S -50")

# Send follow-up tasks
terminal(command="tmux send-keys -t claude-work 'Now add unit tests for the new JWT code' Enter")

# Exit when done
terminal(command="tmux send-keys -t claude-work '/exit' Enter")
```

**When to use interactive mode:**
- Multi-turn iterative work (refactor → review → fix → test cycle)
- Tasks requiring human-in-the-loop decisions
- Exploratory coding sessions
- When you need to use Claude's slash commands (`/compact`, `/review`, `/model`)

## PTY Dialog Handling (CRITICAL for Interactive Mode)

Claude Code presents up to two confirmation dialogs on first launch. You MUST handle these via tmux send-keys:

### Dialog 1: Workspace Trust (first visit to a directory)
```
❯ 1. Yes, I trust this folder    ← DEFAULT (just press Enter)
  2. No, exit
```
**Handling:** `tmux send-keys -t <session> Enter` — default selection is correct.

### Dialog 2: Bypass Permissions Warning (only with --dangerously-skip-permissions)
```
❯ 1. No, exit                    ← DEFAULT (WRONG choice!)
  2. Yes, I accept
```
**Handling:** Must navigate DOWN first, then Enter:
```
tmux send-keys -t <session> Down && sleep 0.3 && tmux send-keys -t <session> Enter
```

### Robust Dialog Handling Pattern
```
# Launch with permissions bypass
terminal(command="tmux send-keys -t claude-work 'claude --dangerously-skip-permissions \"your task\"' Enter")

# Handle trust dialog (Enter for default "Yes")
terminal(command="sleep 4 && tmux send-keys -t claude-work Enter")

# Handle permissions dialog (Down then Enter for "Yes, I accept")
terminal(command="sleep 3 && tmux send-keys -t claude-work Down && sleep 0.3 && tmux send-keys -t claude-work Enter")

# Now wait for Claude to work
terminal(command="sleep 15 && tmux capture-pane -t claude-work -p -S -60")
```

**Note:** After the first trust acceptance for a directory, the trust dialog won't appear again. Only the permissions dialog recurs each time you use `--dangerously-skip-permissions`.

## CLI Subcommands

| Subcommand | Purpose |
|------------|---------|
| `claude` | Start interactive REPL |
| `claude "query"` | Start REPL with initial prompt |
| `claude -p "query"` | Print mode (non-interactive, exits when done) |
| `cat file \| claude -p "query"` | Pipe content as stdin context |
| `claude -c` | Continue the most recent conversation in this directory |
| `claude -r "id"` | Resume a specific session by ID or name |
| `claude auth login` | Sign in (add `--console` for API billing, `--sso` for Enterprise) |
| `claude auth status` | Check login status (returns JSON; `--text` for human-readable) |
| `claude mcp add <name> -- <cmd>` | Add an MCP server |
| `claude mcp list` | List configured MCP servers |
| `claude mcp remove <name>` | Remove an MCP server |
| `claude agents` | List configured agents |
| `claude doctor` | Run health checks on installation and auto-updater |
| `claude update` / `claude upgrade` | Update Claude Code to latest version |
| `claude remote-control` | Start server to control Claude from claude.ai or mobile app |
| `claude install [target]` | Install native build (stable, latest, or specific version) |
| `claude setup-token` | Set up long-lived auth token (requires subscription) |
| `claude plugin` / `claude plugins` | Manage Claude Code plugins |
| `claude auto-mode` | Inspect auto mode classifier configuration |

## Print Mode Deep Dive

### Structured JSON Output
```
terminal(command="claude -p 'Analyze auth.py for security issues' --output-format json --max-turns 5", workdir="/project", timeout=120)
```

Returns a JSON object with:
```json
{
  "type": "result",
  "subtype": "success",
  "result": "The analysis text...",
  "session_id": "75e2167f-...",
  "num_turns": 3,
  "total_cost_usd": 0.0787,
  "duration_ms": 10276,
  "stop_reason": "end_turn",
  "terminal_reason": "completed",
  "usage": { "input_tokens": 5, "output_tokens": 603, ... },
  "modelUsage": { "claude-sonnet-4-6": { "costUSD": 0.078, "contextWindow": 200000 } }
}
```

**Key fields:** `session_id` for resumption, `num_turns` for agentic loop count, `total_cost_usd` for spend tracking, `subtype` for success/error detection (`success`, `error_max_turns`, `error_budget`).

### Streaming JSON Output
For real-time token streaming, use `stream-json` with `--verbose`:
```
terminal(command="claude -p 'Write a summary' --output-format stream-json --verbose --include-partial-messages", timeout=60)
```

Returns newline-delimited JSON events. Filter with jq for live text:
```
claude -p "Explain X" --output-format stream-json --verbose --include-partial-messages | \
  jq -rj 'select(.type == "stream_event" and .event.delta.type? == "text_delta") | .event.delta.text'
```

Stream events include `system/api_retry` with `attempt`, `max_retries`, and `error` fields (e.g., `rate_limit`, `billing_error`).

### Bidirectional Streaming
For real-time input AND output streaming:
```
claude -p "task" --input-format stream-json --output-format stream-json --replay-user-messages
```
`--replay-user-messages` re-emits user messages on stdout for acknowledgment.

### Piped Input
```
# Pipe a file for analysis
terminal(command="cat src/auth.py | claude -p 'Review this code for bugs' --max-turns 1", timeout=60)

# Pipe multiple files
terminal(command="cat src/*.py | claude -p 'Find all TODO comments' --max-turns 1", timeout=60)

# Pipe command output
terminal(command="git diff HEAD~3 | claude -p 'Summarize these changes' --max-turns 1", timeout=60)
```

### JSON Schema for Structured Extraction
```
terminal(command="claude -p 'List all functions in src/' --output-format json --json-schema '{\"type\":\"object\",\"properties\":{\"functions\":{\"type\":\"array\",\"items\":{\"type\":\"string\"}}},\"required\":[\"functions\"]}' --max-turns 5", workdir="/project", timeout=90)
```

Parse `structured_output` from the JSON result. Claude validates output against the schema before returning.

### Session Continuation
```
# Start a task
terminal(command="claude -p 'Start refactoring the database layer' --output-format json --max-turns 10 > /tmp/session.json", workdir="/project", timeout=180)

# Resume with session ID
terminal(command="claude -p 'Continue and add connection pooling' --resume $(cat /tmp/session.json | python3 -c 'import json,sys; print(json.load(sys.stdin)[\"session_id\"])') --max-turns 5", workdir="/project", timeout=120)

# Or resume the most recent session in the same directory
terminal(command="claude -p 'What did you do last time?' --continue --max-turns 1", workdir="/project", timeout=30)

# Fork a session (new ID, keeps history)
terminal(command="claude -p 'Try a different approach' --resume <id> --fork-session --max-turns 10", workdir="/project", timeout=120)
```

### Bare Mode for CI/Scripting
```
terminal(command="claude --bare -p 'Run all tests and report failures' --allowedTools 'Read,Bash' --max-turns 10", workdir="/project", timeout=180)
```

`--bare` skips hooks, plugins, MCP discovery, and CLAUDE.md loading. Fastest startup. Requires `ANTHROPIC_API_KEY` (skips OAuth).

To selectively load context in bare mode:
| To load | Flag |
|---------|------|
| System prompt additions | `--append-system-prompt "text"` or `--append-system-prompt-file path` |
| Settings | `--settings <file-or-json>` |
| MCP servers | `--mcp-config <file-or-json>` |
| Custom agents | `--agents '<json>'` |

### Fallback Model for Overload
```
terminal(command="claude -p 'task' --fallback-model haiku --max-turns 5", timeout=90)
```
Automatically falls back to the specified model when the default is overloaded (print mode only).

## Complete CLI Flags Reference

### Session & Environment
| Flag | Effect |
|------|--------|
| `-p, --print` | Non-interactive one-shot mode (exits when done) |
| `-c, --continue` | Resume most recent conversation in current directory |
| `-r, --resume <id>` | Resume specific session by ID or name (interactive picker if no ID) |
| `--fork-session` | When resuming, create new session ID instead of reusing original |
| `--session-id <uuid>` | Use a specific UUID for the conversation |
| `--no-session-persistence` | Don't save session to disk (print mode only) |
| `--add-dir <paths...>` | Grant Claude access to additional working directories |
| `-w, --worktree [name]` | Run in an isolated git worktree at `.claude/worktrees/<name>` |
| `--tmux` | Create a tmux session for the worktree (requires `--worktree`) |
| `--ide` | Auto-connect to a valid IDE on startup |
| `--chrome` / `--no-chrome` | Enable/disable Chrome browser integration for web testing |
| `--from-pr [number]` | Resume session linked to a specific GitHub PR |
| `--file <specs...>` | File resources to download at startup (format: `file_id:relative_path`) |

### Model & Performance
| Flag | Effect |
|------|--------|
| `--model <alias>` | Model selection: `sonnet`, `opus`, `haiku`, or full name like `claude-sonnet-4-6` |
| `--effort <level>` | Reasoning depth: `low`, `medium`, `high`, `max`, `auto` | Both |
| `--max-turns <n>` | Limit agentic loops (print mode only; prevents runaway) |
| `--max-budget-usd <n>` | Cap API spend in dollars (print mode only) |
| `--fallback-model <model>` | Auto-fallback when default model is overloaded (print mode only) |
| `--betas <betas...>` | Beta headers to include in API requests (API key users only) |

### Permission & Safety
| Flag | Effect |
|------|--------|
| `--dangerously-skip-permissions` | Auto-approve ALL tool use (file writes, bash, network, etc.) |
| `--allow-dangerously-skip-permissions` | Enable bypass as an *option* without enabling it by default |
| `--permission-mode <mode>` | `default`, `acceptEdits`, `plan`, `auto`, `dontAsk`, `bypassPermissions` |
| `--allowedTools <tools...>` | Whitelist specific tools (comma or space-separated) |
| `--disallowedTools <tools...>` | Blacklist specific tools |
| `--tools <tools...>` | Override built-in tool set (`""` = none, `"default"` = all, or tool names) |

### Output & Input Format
| Flag | Effect |
|------|--------|
| `--output-format <fmt>` | `text` (default), `json` (single result object), `stream-json` (newline-delimited) |
| `--input-format <fmt>` | `text` (default) or `stream-json` (real-time streaming input) |
| `--json-schema <schema>` | Force structured JSON output matching a schema |
| `--verbose` | Full turn-by-turn output |
| `--include-partial-messages` | Include partial message chunks as they arrive (stream-json + print) |
| `--replay-user-messages` | Re-emit user messages on stdout (stream-json bidirectional) |

### System Prompt & Context
| Flag | Effect |
|------|--------|
| `--append-system-prompt <text>` | **Add** to the default system prompt (preserves built-in capabilities) |
| `--append-system-prompt-file <path>` | **Add** file contents to the default system prompt |
| `--system-prompt <text>` | **Replace** the entire system prompt (use --append instead usually) |
| `--system-prompt-file <path>` | **Replace** the system prompt with file contents |
| `--bare` | Skip hooks, plugins, MCP discovery, CLAUDE.md, OAuth (fastest startup) |
| `--agents '<json>'` | Define custom subagents dynamically as JSON |
| `--mcp-config <path>` | Load MCP servers from JSON file (repeatable) |
| `--strict-mcp-config` | Only use MCP servers from `--mcp-config`, ignoring all other MCP configs |
| `--settings <file-or-json>` | Load additional settings from a JSON file or inline JSON |
| `--setting-sources <sources>` | Comma-separated sources to load: `user`, `project`, `local` |
| `--plugin-dir <paths...>` | Load plugins from directories for this session only |
| `--disable-slash-commands` | Disable all skills/slash commands |

### Debugging
| Flag | Effect |
|------|--------|
| `-d, --debug [filter]` | Enable debug logging with optional category filter (e.g., `"api,hooks"`, `"!1p,!file"`) |
| `--debug-file <path>` | Write debug logs to file (implicitly enables debug mode) |

### Agent Teams
| Flag | Effect |
|------|--------|
| `--teammate-mode <mode>` | How agent teams display: `auto`, `in-process`, or `tmux` |
| `--brief` | Enable `SendUserMessage` tool for agent-to-user communication |

### Tool Name Syntax for --allowedTools / --disallowedTools
```
Read                    # All file reading
Edit                    # File editing (existing files)
Write                   # File creation (new files)
Bash                    # All shell commands
Bash(git *)             # Only git commands
Bash(git commit *)      # Only git commit commands
Bash(npm run lint:*)    # Pattern matching with wildcards
WebSearch               # Web search capability
WebFetch                # Web page fetching
mcp__<server>__<tool>   # Specific MCP tool
```

## Settings & Configuration

### Settings Hierarchy (highest to lowest priority)
1. **CLI flags** — override everything
2. **Local project:** `.claude/settings.local.json` (personal, gitignored)
3. **Project:** `.claude/settings.json` (shared, git-tracked)
4. **User:** `~/.claude/settings.json` (global)

### Permissions in Settings
```json
{
  "permissions": {
    "allow": ["Bash(npm run lint:*)", "WebSearch", "Read"],
    "ask": ["Write(*.ts)", "Bash(git push*)"],
    "deny": ["Read(.env)", "Bash(rm -rf *)"]
  }
}
```

### Memory Files (CLAUDE.md) Hierarchy
1. **Global:** `~/.claude/CLAUDE.md` — applies to all projects
2. **Project:** `./CLAUDE.md` — project-specific context (git-tracked)
3. **Local:** `.claude/CLAUDE.local.md` — personal project overrides (gitignored)

Use the `#` prefix in interactive mode to quickly add to memory: `# Always use 2-space indentation`.

## Interactive Session: Slash Commands

### Session & Context
| Command | Purpose |
|---------|---------|
| `/help` | Show all commands (including custom and MCP commands) |
| `/compact [focus]` | Compress context to save tokens; CLAUDE.md survives compaction. E.g., `/compact focus on auth logic` |
| `/clear` | Wipe conversation history for a fresh start |
| `/context` | Visualize context usage as a colored grid with optimization tips |
| `/cost` | View token usage with per-model and cache-hit breakdowns |
| `/resume` | Switch to or resume a different session |
| `/rewind` | Revert to a previous checkpoint in conversation or code |
| `/btw <question>` | Ask a side question without adding to context cost |
| `/status` | Show version, connectivity, and session info |
| `/todos` | List tracked action items from the conversation |
| `/exit` or `Ctrl+D` | End session |

### Development & Review
| Command | Purpose |
|---------|---------|
| `/review` | Request code review of current changes |
| `/security-review` | Perform security analysis of current changes |
| `/plan [description]` | Enter Plan mode with auto-start for task planning |
| `/loop [interval]` | Schedule recurring tasks within the session |
| `/batch` | Auto-create worktrees for large parallel changes (5-30 worktrees) |

### Configuration & Tools
| Command | Purpose |
|---------|---------|
| `/model [model]` | Switch models mid-session (use arrow keys to adjust effort) |
| `/effort [level]` | Set reasoning effort: `low`, `medium`, `high`, `max`, or `auto` |
| `/init` | Create a CLAUDE.md file for project memory |
| `/memory` | Open CLAUDE.md for editing |
| `/config` | Open interactive settings configuration |
| `/permissions` | View/update tool permissions |
| `/agents` | Manage specialized subagents |
| `/mcp` | Interactive UI to manage MCP servers |
| `/add-dir` | Add additional working directories (useful for monorepos) |
| `/usage` | Show plan limits and rate limit status |
| `/voice` | Enable push-to-talk voice mode (20 languages; hold Space to record, release to send) |
| `/release-notes` | Interactive picker for version release notes |

### Custom Slash Commands
Create `.claude/commands/<name>.md` (project-shared) or `~/.claude/commands/<name>.md` (personal):

```markdown
# .claude/commands/deploy.md
Run the deploy pipeline:
1. Run all tests
2. Build the Docker image
3. Push to registry
4. Update the $ARGUMENTS environment (default: staging)
```

Usage: `/deploy production` — `$ARGUMENTS` is replaced with the user's input.

### Skills (Natural Language Invocation)
Unlike slash commands (manually invoked), skills in `.claude/skills/` are markdown guides that Claude invokes automatically via natural language when the task matches:

```markdown
# .claude/skills/database-migration.md
When asked to create or modify database migrations:
1. Use Alembic for migration generation
2. Always create a rollback function
3. Test migrations against a local database copy
```

## Interactive Session: Keyboard Shortcuts

### General Controls
| Key | Action |
|-----|--------|
| `Ctrl+C` | Cancel current input or generation |
| `Ctrl+D` | Exit session |
| `Ctrl+R` | Reverse search command history |
| `Ctrl+B` | Background a running task |
| `Ctrl+V` | Paste image into conversation |
| `Ctrl+O` | Transcript mode — see Claude's thinking process |
| `Ctrl+G` or `Ctrl+X Ctrl+E` | Open prompt in external editor |
| `Esc Esc` | Rewind conversation or code state / summarize |

### Mode Toggles
| Key | Action |
|-----|--------|
| `Shift+Tab` | Cycle permission modes (Normal → Auto-Accept → Plan) |
| `Alt+P` | Switch model |
| `Alt+T` | Toggle thinking mode |
| `Alt+O` | Toggle Fast Mode |

### Multiline Input
| Key | Action |
|-----|--------|
| `\` + `Enter` | Quick newline |
| `Shift+Enter` | Newline (alternative) |
| `Ctrl+J` | Newline (alternative) |

### Input Prefixes
| Prefix | Action |
|--------|--------|
| `!` | Execute bash directly, bypassing AI (e.g., `!npm test`). Use `!` alone to toggle shell mode. |
| `@` | Reference files/directories with autocomplete (e.g., `@./src/api/`) |
| `#` | Quick add to CLAUDE.md memory (e.g., `# Use 2-space indentation`) |
| `/` | Slash commands |

### Pro Tip: "ultrathink"
Use the keyword "ultrathink" in your prompt for maximum reasoning effort on a specific turn. This triggers the deepest thinking mode regardless of the current `/effort` setting.

## PR Review Pattern

### Quick Review (Print Mode)
```
terminal(command="cd /path/to/repo && git diff main...feature-branch | claude -p 'Review this diff for bugs, security issues, and style problems. Be thorough.' --max-turns 1", timeout=60)
```

### Deep Review (Interactive + Worktree)
```
terminal(command="tmux new-session -d -s review -x 140 -y 40")
terminal(command="tmux send-keys -t review 'cd /path/to/repo && claude -w pr-review' Enter")
terminal(command="sleep 5 && tmux send-keys -t review Enter")  # Trust dialog
terminal(command="sleep 2 && tmux send-keys -t review 'Review all changes vs main. Check for bugs, security issues, race conditions, and missing tests.' Enter")
terminal(command="sleep 30 && tmux capture-pane -t review -p -S -60")
```

### PR Review from Number
```
terminal(command="claude -p 'Review this PR thoroughly' --from-pr 42 --max-turns 10", workdir="/path/to/repo", timeout=120)
```

### Claude Worktree with tmux
```
terminal(command="claude -w feature-x --tmux", workdir="/path/to/repo")
```
Creates an isolated git worktree at `.claude/worktrees/feature-x` AND a tmux session for it. Uses iTerm2 native panes when available; add `--tmux=classic` for traditional tmux.

## Parallel Claude Instances

Run multiple independent Claude tasks simultaneously:

```
# Task 1: Fix backend
terminal(command="tmux new-session -d -s task1 -x 140 -y 40 && tmux send-keys -t task1 'cd ~/project && claude -p \"Fix the auth bug in src/auth.py\" --allowedTools \"Read,Edit\" --max-turns 10' Enter")

# Task 2: Write tests
terminal(command="tmux new-session -d -s task2 -x 140 -y 40 && tmux send-keys -t task2 'cd ~/project && claude -p \"Write integration tests for the API endpoints\" --allowedTools \"Read,Write,Bash\" --max-turns 15' Enter")

# Task 3: Update docs
terminal(command="tmux new-session -d -s task3 -x 140 -y 40 && tmux send-keys -t task3 'cd ~/project && claude -p \"Update README.md with the new API endpoints\" --allowedTools \"Read,Edit\" --max-turns 5' Enter")

# Monitor all
terminal(command="sleep 30 && for s in task1 task2 task3; do echo '=== '$s' ==='; tmux capture-pane -t $s -p -S -5 2>/dev/null; done")
```

## CLAUDE.md — Project Context File

Claude Code auto-loads `CLAUDE.md` from the project root. Use it to persist project context:

```markdown
# Project: My API

## Architecture
- FastAPI backend with SQLAlchemy ORM
- PostgreSQL database, Redis cache
- pytest for testing with 90% coverage target

## Key Commands
- `make test` — run full test suite
- `make lint` — ruff + mypy
- `make dev` — start dev server on :8000

## Code Standards
- Type hints on all public functions
- Docstrings in Google style
- 2-space indentation for YAML, 4-space for Python
- No wildcard imports
```

**Be specific.** Instead of "Write good code", use "Use 2-space indentation for JS" or "Name test files with `.test.ts` suffix." Specific instructions save correction cycles.

### Rules Directory (Modular CLAUDE.md)
For projects with many rules, use the rules directory instead of one massive CLAUDE.md:
- **Project rules:** `.claude/rules/*.md` — team-shared, git-tracked
- **User rules:** `~/.claude/rules/*.md` — personal, global

Each `.md` file in the rules directory is loaded as additional context. This is cleaner than cramming everything into a single CLAUDE.md.

### Auto-Memory
Claude automatically stores learned project context in `~/.claude/projects/<project>/memory/`.
- **Limit:** 25KB or 200 lines per project
- This is separate from CLAUDE.md — it's Claude's own notes about the project, accumulated across sessions

## Custom Subagents

Define specialized agents in `.claude/agents/` (project), `~/.claude/agents/` (personal), or via `--agents` CLI flag (session):

### Agent Location Priority
1. `.claude/agents/` — project-level, team-shared
2. `--agents` CLI flag — session-specific, dynamic
3. `~/.claude/agents/` — user-level, personal

### Creating an Agent
```markdown
# .claude/agents/security-reviewer.md
---
name: security-reviewer
description: Security-focused code review
model: opus
tools: [Read, Bash]
---
You are a senior security engineer. Review code for:
- Injection vulnerabilities (SQL, XSS, command injection)
- Authentication/authorization flaws
- Secrets in code
- Unsafe deserialization
```

Invoke via: `@security-reviewer review the auth module`

### Dynamic Agents via CLI
```
terminal(command="claude --agents '{\"reviewer\": {\"description\": \"Reviews code\", \"prompt\": \"You are a code reviewer focused on performance\"}}' -p 'Use @reviewer to check auth.py'", timeout=120)
```

Claude can orchestrate multiple agents: "Use @db-expert to optimize queries, then @security to audit the changes."

## Hooks — Automation on Events

Configure in `.claude/settings.json` (project) or `~/.claude/settings.json` (global):

```json
{
  "hooks": {
    "PostToolUse": [{
      "matcher": "Write(*.py)",
      "hooks": [{"type": "command", "command": "ruff check --fix $CLAUDE_FILE_PATHS"}]
    }],
    "PreToolUse": [{
      "matcher": "Bash",
      "hooks": [{"type": "command", "command": "if echo \"$CLAUDE_TOOL_INPUT\" | grep -q 'rm -rf'; then echo 'Blocked!' && exit 2; fi"}]
    }],
    "Stop": [{
      "hooks": [{"type": "command", "command": "echo 'Claude finished a response' >> /tmp/claude-activity.log"}]
    }]
  }
}
```

### All 8 Hook Types
| Hook | When it fires | Common use |
|------|--------------|------------|
| `UserPromptSubmit` | Before Claude processes a user prompt | Input validation, logging |
| `PreToolUse` | Before tool execution | Security gates, block dangerous commands (exit 2 = block) |
| `PostToolUse` | After a tool finishes | Auto-format code, run linters |
| `Notification` | On permission requests or input waits | Desktop notifications, alerts |
| `Stop` | When Claude finishes a response | Completion logging, status updates |
| `SubagentStop` | When a subagent completes | Agent orchestration |
| `PreCompact` | Before context memory is cleared | Backup session transcripts |
| `SessionStart` | When a session begins | Load dev context (e.g., `git status`) |

### Hook Environment Variables
| Variable | Content |
|----------|---------|
| `CLAUDE_PROJECT_DIR` | Current project path |
| `CLAUDE_FILE_PATHS` | Files being modified |
| `CLAUDE_TOOL_INPUT` | Tool parameters as JSON |

### Security Hook Examples
```json
{
  "PreToolUse": [{
    "matcher": "Bash",
    "hooks": [{"type": "command", "command": "if echo \"$CLAUDE_TOOL_INPUT\" | grep -qE 'rm -rf|git push.*--force|:(){ :|:& };:'; then echo 'Dangerous command blocked!' && exit 2; fi"}]
  }]
}
```

## MCP Integration

Add external tool servers for databases, APIs, and services:

```
# GitHub integration
terminal(command="claude mcp add -s user github -- npx @modelcontextprotocol/server-github", timeout=30)

# PostgreSQL queries
terminal(command="claude mcp add -s local postgres -- npx @anthropic-ai/server-postgres --connection-string postgresql://localhost/mydb", timeout=30)

# Puppeteer for web testing
terminal(command="claude mcp add puppeteer -- npx @anthropic-ai/server-puppeteer", timeout=30)
```

### MCP Scopes
| Flag | Scope | Storage |
|------|-------|---------|
| `-s user` | Global (all projects) | `~/.claude.json` |
| `-s local` | This project (personal) | `.claude/settings.local.json` (gitignored) |
| `-s project` | This project (team-shared) | `.claude/settings.json` (git-tracked) |

### MCP in Print/CI Mode
```
terminal(command="claude --bare -p 'Query database' --mcp-config mcp-servers.json --strict-mcp-config", timeout=60)
```
`--strict-mcp-config` ignores all MCP servers except those from `--mcp-config`.

Reference MCP resources in chat: `@github:issue://123`

### MCP Limits & Tuning
- **Tool descriptions:** 2KB cap per server for tool descriptions and server instructions
- **Result size:** Default capped; use `maxResultSizeChars` annotation to allow up to **500K** characters for large outputs
- **Output tokens:** `export MAX_MCP_OUTPUT_TOKENS=50000` — cap output from MCP servers to prevent context flooding
- **Transports:** `stdio` (local process), `http` (remote), `sse` (server-sent events)

## Monitoring Interactive Sessions

### Reading the TUI Status
```
# Periodic capture to check if Claude is still working or waiting for input
terminal(command="tmux capture-pane -t dev -p -S -10")
```

Look for these indicators:
- `❯` at bottom = waiting for your input (Claude is done or asking a question)
- `●` lines = Claude is actively using tools (reading, writing, running commands)
- `⏵⏵ bypass permissions on` = status bar showing permissions mode
- `◐ medium · /effort` = current effort level in status bar
- `ctrl+o to expand` = tool output was truncated (can be expanded interactively)

### Context Window Health
Use `/context` in interactive mode to see a colored grid of context usage. Key thresholds:
- **< 70%** — Normal operation, full precision
- **70-85%** — Precision starts dropping, consider `/compact`
- **> 85%** — Hallucination risk spikes significantly, use `/compact` or `/clear`

## Environment Variables

| Variable | Effect |
|----------|--------|
| `ANTHROPIC_API_KEY` | API key for authentication (alternative to OAuth) |
| `CLAUDE_CODE_EFFORT_LEVEL` | Default effort: `low`, `medium`, `high`, `max`, or `auto` |
| `MAX_THINKING_TOKENS` | Cap thinking tokens (set to `0` to disable thinking entirely) |
| `MAX_MCP_OUTPUT_TOKENS` | Cap output from MCP servers (default varies; set e.g., `50000`) |
| `CLAUDE_CODE_NO_FLICKER=1` | Enable alt-screen rendering to eliminate terminal flicker |
| `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB` | Strip credentials from sub-processes for security |

## Cost & Performance Tips

1. **Use `--max-turns`** in print mode to prevent runaway loops. Start with 5-10 for most tasks.
2. **Use `--max-budget-usd`** for cost caps. Note: minimum ~$0.05 for system prompt cache creation.
3. **Use `--effort low`** for simple tasks (faster, cheaper). `high` or `max` for complex reasoning.
4. **Use `--bare`** for CI/scripting to skip plugin/hook discovery overhead.
5. **Use `--allowedTools`** to restrict to only what's needed (e.g., `Read` only for reviews).
6. **Use `/compact`** in interactive sessions when context gets large.
7. **Pipe input** instead of having Claude read files when you just need analysis of known content.
8. **Use `--model haiku`** for simple tasks (cheaper) and `--model opus` for complex multi-step work.
9. **Use `--fallback-model haiku`** in print mode to gracefully handle model overload.
10. **Start new sessions for distinct tasks** — sessions last 5 hours; fresh context is more efficient.
11. **Use `--no-session-persistence`** in CI to avoid accumulating saved sessions on disk.

## Pitfalls & Gotchas

1. **Interactive mode REQUIRES tmux** — Claude Code is a full TUI app. Using `pty=true` alone in Hermes terminal works but tmux gives you `capture-pane` for monitoring and `send-keys` for input, which is essential for orchestration.
2. **`~/.local/bin/claude` symlink may be a Java wrapper** — see "CRITICAL pitfall: the `~/.local/bin/claude` symlink" above. Use `~/.local/share/claude/versions/<v>` directly.
3. **Multi-line `tmux send-keys` mangles prompts with shell metacharacters** — use `load-buffer` + `paste-buffer` from a temp file. See "CRITICAL pitfall" in Mode 0.
4. **`/clear` between triage rounds** — never send a real prompt into a session that has stale queued diagnostics.
5. **`--dangerously-skip-permissions` dialog defaults to "No, exit"** — you must send Down then Enter to accept. Print mode (`-p`) skips this entirely.
6. **`--max-budget-usd` minimum is ~$0.05** — system prompt cache creation alone costs this much. Setting lower will error immediately.
7. **`--max-turns` is print-mode only** — ignored in interactive sessions.
8. **Claude may use `python` instead of `python3`** — on systems without a `python` symlink, Claude's bash commands will fail on first try but it self-corrects.
9. **Session resumption requires same directory** — `--continue` finds the most recent session for the current working directory.
10. **`--json-schema` needs enough `--max-turns`** — Claude must read files before producing structured output, which takes multiple turns.
11. **Trust dialog only appears once per directory** — first-time only, then cached.
12. **Background tmux sessions persist** — always clean up with `tmux kill-session -t <name>` when done.
13. **Slash commands (like `/commit`) only work in interactive mode** — in `-p` mode, describe the task in natural language instead.
14. **`--bare` skips OAuth** — requires `ANTHROPIC_API_KEY` env var or an `apiKeyHelper` in settings.
15. **Context degradation is real** — AI output quality measurably degrades above 70% context window usage. Monitor with `/context` and proactively `/compact`.
16. **In Mode 0 (consult channel), do NOT let Claude run test suites or builds** — Claude should reason and use Read/Grep/Glob. Long-running execution goes in `terminal(background=true)` outside the tmux session. Violation: Claude Code ran `pytest` for 9+ minutes inside a consult session and blocked Otto from responding.
17. **CRITICAL: Never dump raw `capture-pane` output into chat while monitoring.** (burnt 2026-06-20) The user said "Brief" after 3 consecutive messages containing full pane dumps. The raw capture is for YOU to read — the user only wants the material update: what Claude found, what tool calls it made, what conclusions it reached. A one-liner like "Claude found no hang — suite runs in 149s, now profiling with `--durations=25`" is sufficient between milestones. Only surface the full context when Claude is DONE and you're presenting the handback. Dumping raw pane output while Claude works is noise and frustration.

## Rules for Hermes Agents

1. **Otto's default is Mode 0 (continuous consult channel)** — coordinator mode, not executor. Open a persistent tmux session and drive it with full context for any non-trivial issue. One-off print mode is for unattended/CI tasks only.
2. **In Mode 0, Claude reasons; Hermes orchestrates** — Claude uses Read/Grep/Glob/Bash, but long-running execution (test suites, builds, daemon runs) goes in `terminal(background=true)` outside the tmux session, not delegated to Claude.
3. **Prefer print mode (`-p`) for single-shot unattended tasks** — cleaner, no dialog handling, structured output.
4. **Use tmux for multi-turn interactive work** — the only reliable way to orchestrate the TUI.
5. **Always set `workdir`** — keep Claude focused on the right project directory.
6. **Set `--max-turns` in print mode** — prevents infinite loops and runaway costs.
7. **Monitor tmux sessions** — use `tmux capture-pane -t <session> -p -S -50` to check progress.
8. **Look for the `❯` prompt** — indicates Claude is waiting for input (done or asking a question).
9. **Clean up tmux sessions** — kill them when done to avoid resource leaks.
10. **Report results to user — distill, don't dump.** After completion, summarize what Claude found and what changed. Never paste raw `capture-pane` output into chat while Claude is working — it's noise. The user wants the material update (new tool calls, conclusions, findings), not a full pane dump. A one-line status is fine between milestones: "Claude running `--durations=25`, no hang found yet." See CRITICAL pitfall below.
11. **Don't kill slow sessions** — Claude may be doing multi-step work; check progress instead.
12. **Use `--allowedTools`** — restrict capabilities to what the task actually needs.
