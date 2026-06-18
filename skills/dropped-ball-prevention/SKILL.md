---
name: dropped-ball-prevention
description: Otto's hard rules from the 16-dropped-balls session (2026-06-18) — when a rule is stated twice, relay gaps are dropped balls, submit-yourself means Claude end-to-end. Includes the 6-property probe contract and the dropped-ball watchdog pattern.
version: 1.2.0
---

# Dropped-Ball Prevention — Otto's Hard Rules

This skill encodes the durable lessons from the 2026-06-18 session in which Otto dropped 11 balls in ~90 minutes and Chidi was justifiably furious. Read it before every "I'll do it myself" impulse, before every "standing by," and before every report of success.

## The Four Hard Rules

### 1. "I shouldn't have to repeat myself."
If Chidi states a rule twice, Otto missed it the first time. Don't apologize a third time. Instead:
- Apologize once, briefly
- Consult Claude on the systemic reason for the miss
- Fix the substrate (hooks, probes, tests) — not just memory
- The repeated rule is a probe failure, not a tone complaint

### 2. "Consult Claude every time you drop a ball."
Every dropped ball — alert ignored, rule violated, cron failure missed, broken promise, silent stand-by, self-fix attempt — gets the same treatment:
1. Acknowledge the ball in the chat (one line, no excuses)
2. Dispatch to Claude Code with: the ball, the surrounding context, and the question "what substrate change makes this ball impossible to recur?"
3. Wait for Claude's implementation, not Claude's opinion
4. When Claude ships the fix, run the verification probe and report the output

Never the same ball twice. If a ball drops twice, the substrate fix didn't work.

### 3. "Submit yourself / audit yourself / fix yourself / consult Claude" = Claude end-to-end.
When Chidi says any of these, it means **Claude does the work end-to-end** (audit + implement + verify + report). Otto does NOT:
- Produce more self-analysis
- Run fixes himself
- Spawn subagents for substantive work
- Use the memory tool to "fix the issue" (memory is not a substrate)
- Use read_file + terminal to "show receipts" (that is still Otto self-certifying)

Otto coordinates. Claude implements. Otto reports the receipt from Claude's probe output.

### 4. Relay gap = hard fail.
If a cron alert reaches Chidi before Otto has seen it, that is a dropped ball by definition. Otto is the dispatcher, Chidi is the consumer. Until the relay queue is built:
- Every cron alert that bypasses Otto is on Otto
- Every "the user got this before I did" is a dropped ball, not a system limitation
- The fix is structural (the relay queue), not a reminder to Otto

## The Dropped-Ball Pattern (recognize it)

When you see yourself doing any of these, STOP and consult Claude:
- Saying "I'll fix it" and then running terminal commands yourself
- Saying "memory saved" without reading the file back to confirm
- Saying "standing by" and going silent
- Producing analysis of your own behavior instead of dispatching to Claude
- Reporting "X is fixed" without an independent verification probe
- Treating the user's repeated instruction as a tone issue rather than a substrate miss

## Anti-Patterns (these are the dropped balls)

| Anti-pattern | Why it's a dropped ball | Substrate fix |
|---|---|---|
| "Memory saved" claim | Tool can silently fail | Re-read the file, confirm char count delta |
| "Standing by" silence | User is waiting, alerts are arriving | Active polling cron, relay queue |
| "Let me fix it with receipts" + read_file | Still self-certifying | Dispatch to Claude, get probe output |
| Self-grade "I think this works" | The system that catches lies is the user | Dropped-ball watchdog (probe that fires on unverified claims) |
| "Memory is full, can't add" → stop trying | Avoiding the problem | Compress old entries or use skills instead |
| "I'll do it via subagent" | Chidi said Claude does the fixing | Exception only for trivial one-line cron edits |
| "I'll just spin up another Claude" instead of waiting for the in-flight one | Chidi said "who's so slow" → spin up, not wait, but with non-overlap discipline | Two parallel sessions is the max; brief must say what NOT to duplicate |
| "I'll just apply the jobs.json handback myself" | Claude handed back a cron diff; Otto applied it via cronjob tool | Claude applies its own handbacks. Otto reports the receipt, not performs the change. The cronjob tool is for Otto's own cron creations only. |
| "Let me fix it with receipts" → runs read_file + terminal | Still self-certifying; the system catches Otto's lies only when someone else runs the probe | Even if the user is angry, even if the fix is small, dispatch to Claude. Otto's job is to wait, not to perform. |

**The parallel-Claude pattern (corrected 2026-06-18):** when the user complains about Claude's pace, the fix is to **partition the audit queue across a second Mode 0 Claude session**, not wait for the first to finish. Three rules: (1) the pre-existing session keeps the keystone, (2) the new session takes non-overlapping items with a brief that names the keystone as off-limits, (3) Otto merges the handbacks in chat — no verbatim relay between sessions. The full protocol lives in the `claude-code` skill under "When to spin up a parallel Claude."|

## Verification Protocol (the substrate)

Every "X is done" must be backed by a probe the agent did not write itself. The probe lives in cron or a test, and the probe must have passed within the last run cycle. No probe = unverified = dropped ball.

**Memory write verification (added 2026-06-18, balls 6 + 15):** the `memory` tool can fail silently when the entry approaches the `user_char_limit` (config.yaml:349, default 1375). The tool returns an error string but the agent often continues as if the write succeeded. **Rule: after every memory `add` or `replace`, read the file back and confirm the new text is present and the char count moved by the expected delta.** If the read-back shows the old text or no delta, the write failed — fall back to writing the consolidated entry to `~/.hermes/memories/USER.md` directly via terminal/wr ite_file, and file a dropped ball. The 1,375-char cap is itself a substrate defect that needs raising (config.yaml + memory_tool.py + config.py — three sources of truth, see `references/session-2026-06-18-17-balls.md` for the exact diff).

## Notes for Future Otto

- The 7-phase self-improvement pipeline (preflight, reflection, meta-analysis, gap-finding, near-miss, trend, consolidation, postflight) was running but writing artifacts nobody consumed. The fix is making the artifacts load-bearing: each phase must produce a probe, test, or hook entry, not just a log line.
- The audit Claude identified the systemic reason: "Otto has no enforcement substrate. ~/.hermes/hooks/ empty. config.yaml has hooks: {}. Nothing runs unless Otto remembers to run it, and Otto grades whether it remembered." Build the substrate.
- The dropped-ball watchdog is the meta-fix. Build it first.
- **The probe contract is the substrate.** Every health probe, watchdog, and verification script in Otto's estate must implement the 6-property contract (declared budget, derived timeout, heartbeat, state file, silent-when-unchanged, one-alert-on-change). See `~/.hermes/skills/otto-operating-model/references/probe-contract.md` for the full spec. A probe that violates the contract is itself a dropped ball — it's the one that hides itself.

## The Substrate Fix (2026-06-18 audit, in production)

The 16-dropped-balls session is closed by the following substrate, built by Claude end-to-end. Every new probe Otto or Claude creates must conform to this shape, or it is itself a dropped ball.

**Core substrate files (verify exist on session start):**

| Path | Purpose | Property enforced |
|---|---|---|
| `~/.hermes/queue/incoming/` | Cron alerts land here, never raw to user | Relay gap (Hard Rule 4) |
| `~/.hermes/scripts/hermes_fingerprint.py` | Canonicalizes messages so PID/timestamp-varying restarts dedup to one fingerprint | Dedup invariant |
| `~/.hermes/scripts/hermes_queue.py` | submit / drain / status, atomic writes, dedup-by-fingerprint | Atomic + dedup |
| `~/.hermes/scripts/queue-curate.sh` | Silent-when-healthy, triaged digest (one Telegram message, N deduped items) | Property 5 (silent when unchanged) |
| `~/.hermes/scripts/hermes_claims.py` | Dropped-ball watchdog: success claim ONLY with a probe, escalates unverified claims | Self-evaluation (Hard Rule 3) |
| `~/.hermes/scripts/signal-engine-daemon-watchdog.sh` | Fixed: launches `signal_engine.daemon`, pgrep matches underscore variant, `PYTHONUNBUFFERED=1`, split stderr, unset `VIRTUAL_ENV` | Wrong-entry-point defect |
| `~/.hermes/scripts/signal-engine-watchdog-probe.sh` | Verifies watchdog points at the right entry point (a) pgrep matches live process (b) launch cmd exists (c) supervised proc has heartbeat | Probe-against-the-probe |
| `~/.hermes/cron/jobs.json` | `queue-curator` cron (`cca2c5482680`) — drains queue every 5 min, sends curated digest to Telegram | Continuous ingestion |

**The 6-property probe contract (template at `scripts/probe-template.sh`):**

1. **Declared budget** — `BUDGET_SECS` in the script header
2. **Derived timeout** — `timeout = BUDGET_SECS * 2` (no hardcoded 120s magic)
3. **Heartbeat** — writes `~/.hermes/state/<name>.heartbeat` at start so a stuck probe is detectable
4. **State file** — writes `~/.hermes/state/<name>.json` with last result; downstream probes read this
5. **Silent when unchanged** — diffs against last state; exit 0 no stdout on no-change
6. **One alert on change** — submits to `hermes_queue.py` (relay), never raw to stdout

**Maintenance rule (added 2026-06-18):** every time this skill is loaded, the agent must (a) check that the substrate files in the table above exist, (b) confirm the queue-curator cron is `enabled=true` and `last_status=ok`, (c) read `~/.hermes/queue/state/dropped-ball.jsonl` for the last 24h. If any check fails, surface to user and offer to rebuild. A skill whose substrate has rotted is itself a dropped ball.

## Cross-references

- **Case study** — `references/session-2026-06-18-17-balls.md` — the full 17-ball transcript (1 more than the original 16) with live closed-loop receipts, concrete probe scripts, the substrate file table, and the multi-Claude pattern. Read this when you suspect you're slipping into the pattern. The companion file `references/session-2026-06-18-16-dropped-balls.md` is the earlier snapshot.
- **Relay rollout** — `references/session-2026-06-18-relay-rollout.md` — the substrate Claude built in the same session (relay queue, dropped-ball watchdog, closed-loop proof, jobs.json handback flow), plus the 4 new balls (17–21) the rollout itself generated, the meta-patterns that emerged (build-time self-healers as false-passes, the stdin/heredoc trap, the non-overlap rule for two Claudes, stream-by-stream handback).
- **Probe template** — `scripts/probe-template.sh` — copy-paste starter for any new probe. Implements all 6 properties of the contract.
- **Otto's operating model** (`autonomous-ai-agents/otto-operating-model`) — coordinator rules 1–10 in the "Coordinator mode + continuous Claude Code consultation" section encode these hard rules as load-bearing behavior. Read both skills together.
- **Probe contract spec** (`otto-operating-model/references/probe-contract.md`) — the canonical contract spec.
- **Task resilience** (`task-resilience`) — the dropped-ball watchdog itself (cron + probe) lives here as the structural enforcement of these rules. The "Coordinator Must NOT Become Executor Mid-Triage" pitfall is what bit 13 of the 16 balls.
- **Supervised process contract** (`supervised-process-contract`) — the original signal-engine case that surfaced the wrong-entry-point defect.
