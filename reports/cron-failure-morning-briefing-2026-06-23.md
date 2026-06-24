# Cron-Failure Root-Cause — morning-briefing TimeoutError (2026-06-23)

## The failure
`CRON_ERROR: morning-briefing errored: TimeoutError: Cron job 'morning-briefing'
idle for 936s (limit 600s) — last activity: waiting for stream response (151s, no chunks yet)`
(recorded in `cron/jobs.json`, job id `3ec1c44b218f`, `last_run_at` 2026-06-23T09:21:53).

## Root cause (proven)
A **transient provider first-byte (TTFB) stream hang** on the agentic job's LLM call,
with **no fast auto-recovery for this provider class**:

1. morning-briefing is agentic (`no_agent: false`) with `model: null` / `provider: null`,
   so it uses the estate default: **`deepseek-v4-pro` via `deepseek`** (`config.yaml:1-3`).
   This is an OpenAI-compatible api_mode, **not** `codex_responses`.
2. The deepseek stream accepted the connection but emitted **no first byte**. The only
   liveness signal during a first-byte wait is the 30s heartbeat at
   `agent/chat_completion_helpers.py:2548-2553`, which emits exactly the recorded message
   `"waiting for stream response (Ns, no chunks yet)"`. Activity last advanced at 151s,
   then froze (stream worker exited into the retry/backoff path, which does not touch
   activity), so idle climbed unchecked.
3. The **no-byte TTFB watchdog** that kills+reconnects a wedged socket in ~seconds is
   **gated to `api_mode == "codex_responses"`** (`agent/chat_completion_helpers.py:280`,
   `_codex_watchdog_enabled = agent.api_mode == "codex_responses"`). deepseek is not codex,
   so the hang was not promptly recovered.
4. The job-level inactivity watchdog (`cron/scheduler.py:1778`, default 600s) eventually
   killed it. Kill landed at 936s, not ~605s — a ~336s overshoot consistent with host-load
   / GIL starvation of the poll loop (5-min load avg ~11.4 at audit time; cf. the recurring
   "Mac overload cascades timeouts" pattern).

## Why this is transient, not systemic
`daily-strategist-audit` (also `no_agent: false`, **same** default `deepseek-v4-pro`) ran
**ok at 10:20:21 the same day** — ~1h after morning-briefing failed. Same provider/model,
green. So the 09:00 failure was a single hung connection, not a provider/config outage.

## Current state — already self-recovered (verified 12:34)
- `morning-briefing`: `enabled=true`, `state=scheduled`, `next_run_at=2026-06-24T09:00:00`.
- No re-fire loop (unlike the 2026-06-19 repo-health case).
- No orphaned process from the hung run (`ps aux | grep morning` → none).
- Gateway alive (heartbeat fresh, mtime 11:53).
So the **immediate condition no longer reproduces** with no intervention.

## What was deliberately NOT done (proof/risk discipline)
- **Did not edit `chat_completion_helpers.py`** to extend the no-byte TTFB reconnect to all
  providers. That is the shared streaming hot path for every LLM call in the estate; the fix
  cannot be proven without reproducing a provider first-byte hang, so shipping it
  autonomously would violate "no PR without proof" and exceeds the spec's `risk_class: low`.
- **Did not hand-edit `cron/jobs.json`** (clearing `last_status=error`): it is gateway-owned
  and actively rewritten (`updated_at` 11:55) — hand-editing under the live gateway is a
  write-race/clobber risk, and the field is cosmetic (job already rescheduled).

## Recommended durable fix (needs founder go — human_decision_required should be TRUE)
Pick one, each with its own repro + integration proof before rollout:
- **A (preferred):** generalize the no-byte/stale-stream reconnect so TTFB hangs on
  openai-compatible providers (deepseek, minimax) trigger the same fast kill+reconnect that
  `codex_responses` already gets — i.e. remove the `codex_responses` gate at
  `chat_completion_helpers.py:280` for the no-byte path, with a tunable timeout.
- **B:** on a cron inactivity-timeout for an idempotent read-only job, fail over to the
  configured fallback provider (`config.yaml:5-7`, minimax / MiniMax-M3) and retry once.
- **C (cheapest, narrowest):** pin morning-briefing to the fallback provider, or set a tight
  per-job `HERMES_CRON_TIMEOUT` so a hang is killed and retried on the next tick rather than
  recorded as a hard error.
