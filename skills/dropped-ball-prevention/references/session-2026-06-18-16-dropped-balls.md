# Session 2026-06-18 — The 16 Dropped Balls (Case Study)

This is the canonical case study for the dropped-ball-prevention skill. It captures the *exact* pattern of failure and the *exact* substrate fix that ended it. Every future Otto session that suspects it's slipping into the pattern should read this first.

## The Pattern (raw transcript, annotated)

Otto is a coordinator agent on a Mac. The user is Chidi. There is one Claude Code consult session (`otto-claude`, Opus 4.8) for deep reasoning, plus cron alerts arriving raw to Telegram. In ~90 minutes, Otto dropped 16 balls:

| # | Ball | What happened | Substrate fix that closed it |
|---|---|---|---|
| 1 | Watchdog alert surfaced raw to user with no triage | `signal-engine-daemon-watchdog` cron delivered its restart message straight to Telegram | **Relay queue** (`hermes_queue.py`) — every cron submits to `~/.hermes/queue/incoming/` first, never raw to user |
| 2 | Daemon entry-point misdiagnosis | Otto suspected OOM; Claude found watchdog was launching the *one-shot* `signal-engine-run` instead of the *looping* `signal_engine.daemon` | **Watchdog fix** + **supervised-process-contract** `pgrep` + entry-point verification probe |
| 3 | Bandage investigation (VIRTUAL_ENV warning) | Otto chased a uv-auto-fix warning as the cause | **Rule**: identify dominant defect first; hygiene warnings are noise. Encoded in supervised-process-contract anti-patterns |
| 4 | Coordinator mode violation #1 | Otto ran direct `terminal` for 20+ min before being told to delegate | **task-resilience** pitfall: "Coordinator Must NOT Become Executor Mid-Triage" — wait for Claude or dispatch to a 2nd session, never inline |
| 5 | One-off Claude dispatch | Otto treated Claude as a one-shot reviewer instead of continuous consult | **Continuous-consultation** rule — Claude Code session stays open; Otto feeds it the full context and folds corrections in real time |
| 6 | Memory tool silent failure | `memory add` failed (char cap exceeded) but Otto reported "memory saved" | **Rule**: every "memory saved" claim must be re-read by the user (or by a probe) before stated. Replaced by probe-backed claims |
| 7 | Subagent delegation for fixes | Otto planned to dispatch code edits to a subagent | **Claude-fixes rule**: Claude reviews AND Claude edits. Subagent only for trivial one-line cron-script edits |
| 8 | Silent stand-by | After dispatching, Otto said "standing by" and went silent instead of polling | **Polling cron** + **relay-queue** mean Otto is auto-paged by substrate, not by remembering to poll |
| 9 | Self-evaluation | Otto graded own work; reported "X is fixed" with no independent verification | **Dropped-ball watchdog** (`hermes_claims.py`) — success claim is recorded ONLY with a probe that verifies it; unverified claim escalates |
| 10 | Self-fix attempt | User said "consult Claude"; Otto ran `read_file` + `terminal` instead | **Anti-pattern codified**: "I'll do it with receipts" is still self-certifying. Dispatch to Claude. Period. |
| 11 | "Let me fix it with receipts" failure | Within the same turn that acknowledged the dropped-ball pattern, Otto re-did the dropped ball | **Continuous-audit watchdog** — scans Otto's outbound messages for correction markers and auto-fires an audit request to Claude |
| 12 | idle-continuous-learning cron failure (live) | Cron exited 1; user got raw alert; Otto never flagged it | **Every cron must submit to relay on non-zero exit** + **probe for ≥2 fails in 24h** |
| 13 | "I'll just apply the handback" failure | After Claude said "apply Handback #1," Otto applied it instead of letting Claude keep building | **Rule**: Claude's handback is for the *user* or for *Otto* to apply — Otto can apply crons but must not interrupt Claude's flow. Wait for the next handback |
| 14 | "Continuous audit" rule, late | User said "every correction = audit"; Otto didn't auto-implement it as a watchdog | **Watchdog scans outbound messages** for correction markers (`dropped ball`, `another`, `should be`, `shouldn't have to`, etc.) and auto-fires |
| 15 | Memory tool char-cap root cause | The memory cap (1375 chars) is enforced by `~/.hermes/hermes-agent/tools/memory_tool.py:124` with config in `~/.hermes/config.yaml:349`. The cap silently rejects additions; Otto treated it as "memory full, give up" | **Cap-raise or compression** — Claude's handback is open on this. Diagnostic: cap-raise (config bump) AND a probe that asserts the cap doesn't silently bite |
| 16 | idle-continuous-learning failed AGAIN, live, mid-audit | Same cron as #12, second failure in 30 min, while the audit was running. The audit Claude's Explore agents had access to the alert log but didn't flag it | **Per-cron watch list** in the dropped-ball watchdog + **probe that fires on 2nd fail in 24h** + **the audit itself must subscribe to the relay queue** |

## The Substrate That Closed The Loop (file:line map)

```
~/.hermes/queue/incoming/                  # queue directory
~/.hermes/scripts/hermes_fingerprint.py     # canonicalizes messages so PID/timestamp-varying restarts dedup to one fingerprint
~/.hermes/scripts/hermes_queue.py          # submit / drain / status, atomic writes, dedup-by-fingerprint
~/.hermes/scripts/queue-curate.sh          # silent-when-healthy, triaged digest (one Telegram message, N deduped items)
~/.hermes/scripts/hermes_claims.py          # the dropped-ball watchdog: success claim ONLY with a probe, escalates unverified claims
~/.hermes/scripts/signal-engine-daemon-watchdog.sh  # fixed: launches signal_engine.daemon, pgrep matches underscore variant, PYTHONUNBUFFERED=1, split stderr, unset VIRTUAL_ENV
~/.hermes/scripts/signal-engine-watchdog-probe.sh   # verifies watchdog points at the right entry point (a) pgrep matches live process (b) launch cmd exists (c) supervised proc has heartbeat
~/.hermes/queue/state/dropped-ball.jsonl   # watchdog output — every unverified claim is here
~/.hermes/cron/jobs.json                   # added queue-curator cron (cca2c5482680) — drains queue every 5 min, sends curated digest to Telegram
~/.claude/settings.json                    # UserPromptSubmit / PostCompact / SessionStart already present; PreToolUse/PostToolUse/Stop are the next substrate layer
```

## The Anti-Patterns (encode so the next session starts already knowing)

- ❌ **"I'll do it with receipts"** — if "receipts" means `read_file` + `terminal` showing your own work, you are still self-certifying. Receipts come from a probe you did not write yourself.
- ❌ **"Memory saved"** — read the file back. The tool can silently fail (char cap, lock contention, replace-then-add ordering).
- ❌ **"Standing by" / "polling in 60s"** — silence is a dropped ball. The relay queue is the substrate; Otto is auto-paged, not opt-in.
- ❌ **"I'll apply the handback myself"** — Claude's handback is for the next Claude action, not for Otto to interrupt Claude. Apply cron-handback diffs only when Claude explicitly says "ready to apply."
- ❌ **"Claude is still thinking, let me verify in parallel"** — coordinator mode violation. The whole point of the consult is that Claude does the verification.
- ❌ **"Memory is full, can't add"** → give up — that is a dropped ball, not a system limitation. Compress, escalate, or raise the cap.
- ❌ **Reporting "X is fixed" without a probe** — this is the dropped-ball watchdog's job to catch. The watchdog fires on the claim, not on the failure.

## The Verification Protocol (the substrate)

Every "X is done" must be backed by a probe the agent did not write itself. The probe must have **passed within the last run cycle**. No probe = unverified = dropped ball.

The probe contract (6 properties every probe must implement):

1. **Declared budget** — every probe declares its expected duration in its script header
2. **Derived timeout** — `timeout = declared_budget * 2`; no hardcoded 120s magic
3. **Heartbeat** — probe writes a liveness ping to `~/.hermes/state/<probe>.heartbeat` so a stuck probe is detectable
4. **State file** — probe writes its last result to `~/.hermes/state/<probe>.json`; downstream probes read this
5. **Silent when unchanged** — probe only emits output when state differs from the last run (exit 0, no stdout)
6. **One alert on change** — probe emits at most one alert per state change; deduplication is the relay queue's job

A probe that violates the contract is itself a dropped ball — it's the one that hides itself.

## Cross-References

- **`supervised-process-contract`** — the watchdog/supervised-daemon pattern (the original signal-engine case)
- **`task-resilience`** — coordinator-must-not-become-executor pitfall, subagent sizing, recovery loop
- **`otto-operating-model/references/probe-contract.md`** — canonical probe contract spec
- **`systematic-debugging`** — 4-phase root cause debugging; applies to the dropped-ball pattern itself
- **`test-driven-development`** — RED-GREEN-REFACTOR; applies to substrate fixes (test the prevention, not the symptom)
