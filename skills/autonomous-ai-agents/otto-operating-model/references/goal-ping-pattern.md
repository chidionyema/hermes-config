# Goal-of-the-Moment Cron Pattern

User demand (2026-06-19 session): a recurring ping that asks "what's the goal
of the moment?" should be delivered by **Otto** (the assistant the user is
talking to), not by a fresh agent that has no relationship with the user.

The naive approach — cron LLM-driven job with auto-delivery — produced a
fresh-agent identity per tick, which the user correctly identified as wrong.

## Correct pattern: no-agent script + `hermes send`

```bash
#!/bin/bash
# goal-of-the-moment.sh — Otto-voice Telegram ping
set -u
output=$(hermes send --to telegram "Otto here — what's the goal of the moment?" 2>&1)
rc=$?
echo "$output"  # for the cron output log
[ "$rc" -ne 0 ] && { echo "DELIVERY FAILED (hermes send exit=$rc)" >&2; exit 1; }
exit 0
```

Cron registration:

```
cronjob action='create' name='goal-of-the-moment' no_agent=True \
  schedule='every 1m' script='goal-of-the-moment.sh'
```

## Critical gotchas (each one was a real bug, fixed 2026-06-19)

### 1. `hermes send --quiet` HANGS (exit 124)

`hermes send` without `--quiet` works fine and prints
`Sent to telegram home channel (chat_id: ...)`. With `--quiet`, the CLI hangs
and is killed by the caller's timeout. **Never use `--quiet` in a cron script.**
Capture the natural stdout to a variable and echo it for the cron log.

### 2. `deliver: origin` causes DOUBLE delivery

If the cron job is `deliver: origin` AND the script calls `hermes send` to
Telegram, the user gets the message twice: once from `hermes send`, once from
the cron scheduler re-sending the script's stdout ("Sent to telegram...").

**Fix:** set `deliver: local` on cron jobs that self-deliver. The script's
output is logged to `~/.hermes/cron/output/<job_id>/` for diagnostics, and the
`hermes send` call is the single source of truth for Telegram delivery.

### 3. LLM-driven cron jobs don't have `send_message` as a tool

An LLM-driven cron prompt that says "call the send_message tool" will fail at
runtime — the agent has no such function-call tool, only the `hermes-telegram`
skill which uses a CLI. Don't try to make the cron LLM send Telegram messages
directly. Use the no-agent + script + `hermes send` pattern.

### 4. cron-scheduler vs my-session timing

`hermes cron list` reports `Last run: ... ok` even if the user never saw the
message — because "ok" means the scheduler tick succeeded, NOT that delivery
landed in the user's hands. Always verify delivery by either:
- Running the script manually and watching for the Telegram message
- Reading `~/.hermes/cron/output/<job_id>/*.md` to see what the cron actually emitted
- Asking the user "did you get the ping?"

## When the user pushes back on cadence

If the user picks a cadence you think is too aggressive (e.g., "every 1
minute"), do NOT re-litigate. Execute the requested cadence. The user's
stated choice overrides your optimization. If it later proves wrong, surface
the evidence, don't preemptively override.

## Manual test (proves the foundation works)

```bash
bash ~/.hermes/scripts/goal-of-the-moment.sh
# expect: "Sent to telegram home channel (chat_id: 8868748055)" and exit 0
```

## One-voice rule (Otto's identity)

The Telegram message must be in Otto's voice ("Otto here — ..."), not a
generic "Cron ping: ..." or "[SILENT]" placeholder. Otto is the relationship
the user has with the system — every ping carries that identity forward.

## WRONG PATTERN (user correction, 2026-08-02)

The goal-ping pattern above was **explicitly rejected** by the user:

> "Rather than asking the goal, you should always be making the telegram
> experience better."

Asking "what's the goal of the moment?" via cron treats Otto as a passive
waiter. Otto is not a waiter — Otto is a coordinator who finds the next
bottleneck and fixes it. Goal-pings produce noise, not progress.

**Action taken (2026-08-02):**
- Removed cron job `goal-of-the-moment` (id `8b3beb82ae6e`).
- Built replacement watchdog `telegram_ux_probe.py` + wrapper
  `telegram-ux-probe.sh` that actively renders 10 public-facing panels and
  reports health/regressions. Watchdog pattern: silent on healthy+unchanged,
  deliver on change/regression.
- Scheduled daily at 06:00 as `telegram-ux-probe-daily` (id `abad59a2f02c`),
  `no_agent=True`, `deliver=local`.

**The replacement scripts live at:**
- `~/.hermes/scripts/telegram_ux_probe.py` — Python probe (the substance)
- `~/.hermes/scripts/telegram-ux-probe.sh` — bash wrapper with hard timeouts

**Generalized rule:** When the user says "make X better," the response is
NOT another cron that asks about X. The response is a watchdog/agent that
actively improves X and only delivers when something has changed or broken.
The output policy is watchdog-pattern: silent on healthy, deliver on signal.

**Lesson for any recurring ping:** If a cron asks the user a question, it is
probably wrong. Cron jobs should do work and surface findings, not solicit
input. The user is busy; Otto's job is to be busy on their behalf.

## Telegram UX watchdog pattern (replacement, 2026-08-02)

The replacement probe implements the **probe contract** from
`references/probe-contract.md` plus the **output-dedup pattern** from
`references/output-dedup-and-state-mirroring.md`:

```python
# Silent on healthy AND unchanged:
#   exit 0, stdout empty → silent
# Deliver on:
#   - state changed (panel count / size / markup differs)
#   - regression detected (text > 4096, row > 8, unbalanced markdown)
#   - panel render crashed
DIGEST_FILE = Path.home() / ".hermes/cache/telegram-ux-probe.digest"
digest = sha256("|".join(deltas)).hexdigest()[:12]
prev = DIGEST_FILE.read_text().strip() if DIGEST_FILE.exists() else ""
if prev == digest and not issues:
    sys.exit(0)  # silent
DIGEST_FILE.write_text(digest)
# emit findings to stdout → bash wrapper delivers via hermes send
```

**Watchdog gotchas learned during this session:**
- **Heredoc + nested Python indentation is fragile.** Mixing `<< 'PY'` with
  indented Python in bash produces broken-indent scripts. Extract the Python
  to its own `.py` file and call it from the bash wrapper.
- **`hermes send` prints "Sent to telegram..." even when stdin is empty.**
  Always guard the bash wrapper with `[ -z "$output" ] && exit 0` BEFORE
  calling `hermes send`. Otherwise the wrapper delivers empty messages on
  every silent tick (false "Sent" logs).
- **Panel return shapes vary.** Some return `(text, rows)`, some
  `(text, bool, rows)`. Normalize before measuring: `rows = next((x for x in
  result if isinstance(x, list) and all(isinstance(r, (list, tuple)) for r
  in x)), [])`.
