# Multi-Session Claude Code Coordination — Reference

Pattern: when one Claude is not enough, run two (or more) Claudes in parallel tmux sessions and orchestrate them from Otto. This file collects concrete recipes and the failure modes that have actually burned us.

## When to use this

- **Live triage + meta-audit** — one Claude investigates, another audits the agent/system that produced the bug. The audit Claude cross-reads the triage Claude's pane via `tmux capture-pane`. Caught in the 2026-06-18 signal-engine incident: audit found that the supervised-process-contract skill was an orphan (documented the fix but no watchdog read it).
- **Live triage + strategist review** — one Claude reasons about a fix, a second Claude (in a separate session) reviews the proposed fix against the codebase. Same cross-pane observation pattern.
- **Multi-domain parallel investigation** — three Claudes, each on a different problem domain (e.g., signal-engine, prospector, lux), all running in parallel with separate `otto-claude-<domain>` session names.

## Launching multiple sessions

```bash
# Naming convention: otto-claude-<domain>-<role?>
tmux new-session -d -s otto-claude-signal-triage -x 160 -y 50
tmux new-session -d -s otto-claude-signal-audit -x 160 -y 50
tmux new-session -d -s otto-claude-prospector -x 160 -y 50

# Each launches the real binary (NOT the broken ~/.local/bin/claude symlink)
# See claude-code SKILL.md "CRITICAL pitfall: the ~/.local/bin/claude symlink"
for session in otto-claude-signal-triage otto-claude-signal-audit otto-claude-prospector; do
  tmux send-keys -t $session '~/.local/share/claude/versions/2.1.181 --dangerously-skip-permissions' Enter
  sleep 4
  tmux send-keys -t $session Enter  # any initial dialog
  sleep 2
  tmux send-keys -t $session '/clear' Enter  # clean slate before real prompt
done
```

## Cross-pane observation (the meta-supervision signal)

Any one Claude can read any other Claude's pane. This is the **only** way Claude-A can see what Claude-B is doing without going through Otto.

```bash
# From inside a Claude session, in a Bash tool call:
tmux capture-pane -t otto-claude-signal-triage -p -S -100 | tail -200
```

The audit prompt should tell the auditor explicitly to do this periodically:

> "Every few minutes, run `tmux capture-pane -t otto-claude-signal-triage -p -S -60` to see what the live triage is finding. If the triage reaches a conclusion you disagree with, raise it in your response. If you find that your own work is now redundant because the triage already covered it, say so and stop."

## Steering discipline (Otto's job)

When you have multiple Claudes running:

1. **Always specify the target session in `tmux send-keys -t <name>`** — never use bare `tmux send-keys`. Bare send goes to whichever pane is "current" in the user's terminal, which is unpredictable.
2. **Clear the input box on BOTH sessions before any disambiguating message.** A common burn: typing into the wrong pane, then trying to "fix" by sending to the right pane — both Claudes now have queued or processed garbled text.
3. **Don't relay verbatim findings between sessions.** If triage says "watchdog is wrong" and audit agrees, Otto reformulates: "Both agree: watchdog supervises the wrong program. I'm relaying to the user." Don't pipe the literal triage output into the audit, or vice versa — each Claude should have its own independent context.
4. **Pause all sessions before asking the user a decision.** `tmux send-keys -t <all> Escape; tmux send-keys -t <all> C-c` then report. Prevents speculative work while the user thinks.
5. **Report the session map in every status update.** "Live triage in `otto-claude-signal-triage` (Phase 2 of 4). Meta-audit in `otto-claude-signal-audit` (recon complete, writing report)." The user and any future agent reading the transcript must be able to reconstruct which session said what.

## Failure modes catalog (with fixes)

### FM-1: paste accumulation (already in claude-code SKILL.md)

**Symptom:** second `paste-buffer` to a pane appends to unsent first paste. Claude receives garbled text.

**Fix:** `Escape; C-a; C-k` before every new paste.

### FM-2: wrong-pane focus

**Symptom:** the user (or Otto) types "fix the watchdog" intending it for the triage session, but the tmux `current-pane` is the audit session. The audit Claude starts editing watchdog scripts that the triage Claude was only diagnosing.

**Fix:** always use `tmux send-keys -t <named-session>`. Set up a tmux status-line config that shows the active session name in green. The default config shows the active window/session at the bottom of each pane, but if you have multiple sessions attached to the same client it can be ambiguous.

### FM-3: race between Otto's relay and Claude's update

**Symptom:** Otto relays a finding to the user, but the source Claude continues to reason and updates its conclusion 5 seconds later. Now the user has stale information.

**Fix:** when relaying a Claude finding, either (a) tell the source Claude to PAUSE before you relay (`tmux send-keys -t triage 'Pause. I'm relaying to the user now.' Enter`), or (b) mark the relay as "as of T+X" with the timestamp captured from the pane.

### FM-4: audit becomes a doer

**Symptom:** audit Claude was briefed "do not act on what you saw in the other pane, just audit." But the audit is so engaged that it starts writing code or making decisions. The meta-supervision becomes the supervision.

**Fix:** the audit prompt must include an explicit "DO NOT edit any files" and "DO NOT run the daemon" constraint, with the same weight as the triage prompt. Same goes for: "If you find a real fix that needs shipping, surface it to Otto — do not apply it."

### FM-5: orphaned subagent from earlier dispatch

**Symptom:** Otto dispatched a subagent (`delegate_task`) hours ago. It's still running, eating context, and the user has no idea.

**Fix:** `process(action='list')` periodically. If a subagent has been running >30s without a checkpoint, kill it (`process(action='kill')`) and re-dispatch with a stage-reporting prompt (see `task-resilience` SKILL.md, "The check-between-stages pattern").

## Naming convention

```
otto-claude-<domain>-<role?>
```

Examples:
- `otto-claude-signal-triage`
- `otto-claude-signal-audit`
- `otto-claude-lux-verify`
- `otto-claude-prospector-gen`

Role is optional but helps when you have 2+ sessions on the same domain. Never reuse a session name — `tmux new-session -d` with an existing name will silently fail (or error), and you'll send keys to a stale session.
