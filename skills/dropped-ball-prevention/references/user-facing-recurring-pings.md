# User-Facing Recurring Pings — Otto Recipe

**Class of work:** any cron job whose deliverable is a message *to* the user that asks a question, prompts a check-in, or reminds them of something Otto would otherwise say in conversation.

**Why this is its own class:** the obvious implementation (`cronjob create` with a prompt) is wrong. It spawns a fresh agent per tick that has no relationship to the user, produces text in a stranger's voice, and adds LLM cost + latency to something that should be a 50ms script call. Chidi called this out directly: *"I want the task to wake you up and you ask me, not the scheduled task asking me."*

**Worked example:** `goal-of-the-moment` cron — fires every 1m, sends "Otto here — what's the goal of the moment?" to Telegram. Job ID `855e0d9fa062`.

## The Recipe (5 steps)

### 1. Decide if it's a ping or a digest

- **Ping** (one short question, no analysis) → always `no_agent=true` + script + `hermes send`
- **Digest** (multi-item summary, prior context, reasoning) → LLM-driven is fine, but the prompt must be self-contained and the output must NOT call `send_message` (the cron wrapper auto-delivers)

If unsure, default to ping. The user can promote it to a digest later.

### 2. Write the script under `~/.hermes/scripts/`

```bash
#!/bin/bash
# <name>.sh — <one-line description>
# Cron ping: <what it asks>.
# Runs under `hermes cron --no-agent`. Exit codes: 0 delivered, non-zero = alert.
set -u

hermes send --to telegram --quiet "<Otto's voice here>" >/dev/null 2>&1
rc=$?

if [ "$rc" -ne 0 ]; then
  echo "DELIVERY FAILED (hermes send exit=$rc)" >&2
  exit 1
fi
exit 0
```

**Pitfall — never call `send_message` from inside the script.** The cron wrapper auto-delivers stdout; double-delivery causes duplicates. The script's job is *only* the `hermes send` call.

**Pitfall — voice matters.** The text is the user-facing artifact. "Otto here — …" is good. "Reminder:" or "Cron ping:" is bad — the user knows it's a cron, the voice should be the *point* of using Otto.

**Pitfall — `hermes send --quiet` HANGS (exit 124 / 30s timeout) in cron-launched scripts (added 2026-06-19).** As of this build, `hermes send --quiet` and `hermes send ... >/dev/null 2>&1` reliably hang in the cron-no-agent context and are killed by the parent `timeout` (cron then reports `error: Script timed out after 120s`). The bare command `hermes send --to telegram "<msg>"` (no `--quiet`, no stdout redirection) exits cleanly with `Sent to telegram home channel (chat_id: ...)` and IS the only currently-working pattern from a script.

**Corrected template (the one that works):**

```bash
#!/bin/bash
set -u
# Capture stdout (don't redirect to /dev/null — that triggers the hang).
output=$(hermes send --to telegram "Otto here — what's the goal of the moment?" 2>&1)
rc=$?
# Echo the captured output so the cron scheduler can deliver it AND so the
# script exits (it would otherwise block on a still-open pipe to the CLI).
echo "$output"
if [ "$rc" -ne 0 ]; then
  echo "DELIVERY FAILED (hermes send exit=$rc)" >&2
  exit 1
fi
exit 0
```

**Diagnosis recipe when a cron-no-agent script "times out" but the same `hermes send` works in your terminal:** (1) reproduce with `timeout 15 bash <script>; echo "exit=$?"` — exit 124 = the hang, (2) strip `--quiet` and `>/dev/null` from the script, capture into a variable and `echo` it, (3) re-test standalone, (4) re-attach to cron. The hang is specific to stdout-suppression paths inside the cron-launched process; interactive shells are unaffected. **Always test the script standalone before wiring cron — this bug only shows up in the cron context.**

### 3. Test the script standalone BEFORE wiring cron

```bash
chmod +x ~/.hermes/scripts/<name>.sh
bash ~/.hermes/scripts/<name>.sh
echo "exit=$?"
```

The user should see the message immediately and you should see `exit=0`. If `exit≠0`, the script is broken — fix it before attaching to cron, otherwise every tick fires a "DELIVERY FAILED" alert.

### 4. Wire the cron job (no_agent, with script)

```bash
cronjob create \
  --name "<name>" \
  --no-agent \
  --schedule "every <Nm>" \
  --script <name>.sh
```

Verify with `hermes cron list | grep -A 8 <name>` — confirm `Mode: no-agent (script stdout delivered directly)` and `Script: <name>.sh`.

### 5. Hand the user the receipt

Reply with: job_id, schedule, next_run_at, the text that was sent, and a note that the user can stop/manage it with "stop reminder <name>". The user can independently verify by waiting for the next tick.

## Anti-Patterns

| Pattern | Why wrong |
|---|---|
| `cronjob create` with a prompt that asks the user a question | Spawns fresh agent per tick; the ping arrives in a stranger's voice; LLM cost per tick |
| Script that calls `send_message` directly | Double-delivery: cron wrapper + script both try to send |
| LLM-driven cron for a literal question | Burns tokens to ask "what's the goal?" — use the script |
| Wiring cron before testing the script standalone | First N ticks fire "DELIVERY FAILED" alerts |
| Cron prompt with `[SILENT]` and content combined | Delivery gets suppressed; user sees nothing |
| Using `deliver: origin` on a no-agent script | Redundant — the script's `hermes send` is the only delivery path; origin would echo the script's stdout back as a second message |
| Calling the script without `set -u` | Hidden variable typos → silent script success → user gets no message |
| Hiding the receipt (job_id) in the response | Receipts-ledger rule: every "I set it up" needs the job_id attached |

## Schedule Sizing

- **Minute-cadence** (every 1m, 5m, 10m) — only for active testing or extremely tight check-ins
- **Hourly** — the safe default for most pings
- **Daily at a fixed time** — for "morning goal," "evening reflection," "weekly review"
- **Idle-conditional** — pair with `idle-continuous-learning` if the ping should only fire when the user has been quiet for ≥N minutes

When the user says "every X" without a unit, default to minutes for X<60, hours for 60≤X<1440, days otherwise. Confirm only if the unit is ambiguous ("every 1" could be 1 minute or 1 hour).

## Substrate Invariants

- The script's exit code is the *only* failure signal the cron watchdog sees. If you bypass `set -u` and the script silently produces empty stdout with exit 0, the system reports "ok" and the user never gets the ping. Always include a non-zero exit on delivery failure.
- A broken ping job that exits 0 is **worse** than a broken ping job that exits 1 — the former hides itself in the "ok" state.
- Receipts for this class of work: (a) `hermes cron list | grep -A 8 <name>` showing `Mode: no-agent`, (b) the output dir `~/.hermes/cron/output/<job_id>/` containing the most recent run, (c) the script's standalone test exit code.

## Related

- `dropped-ball-prevention` SKILL.md — parent rules
- `references/cron-budget-subprocess-pattern.md` — bounding handler subprocess time
- `references/session-2026-06-18-17-balls.md` — the dropped-ball case where proactive gestures were held in working memory instead of scheduled
