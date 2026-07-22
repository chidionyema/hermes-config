# Cron Reliability Patterns

Hermes cron jobs can fail due to:
- **Broken pipe ([Errno 32])** — DeepSeek/API streaming goes silent longer than the gateway's stale timeout (180s). The gateway kills the connection, but the shell pipe to the agent process doesn't report this cleanly.
- **Permission denied** — scripts called by cron must be executable independently of the Hermes profile env.
- **Transient API congestion** — no chunks arriving within 180s.

## Fix: no-agent cron pattern

The single most effective fix: **convert LLM-driven cron jobs to no-agent (script-based) cron jobs.**

The `no_agent=True` pattern on cron jobs:
- Runs the script directly — no LLM call, no token burn, no streaming timeout
- Empty stdout = silent delivery (good for watchdog pattern — only alert when there's something to report)
- Non-zero exit / timeout sends an error alert

### When to convert to no-agent

| Current pattern | Convert to no-agent only if... |
|----------------|-------------------------------|
| Cron agent that reads state and sends a summary | YES — write a Python script that does the same work |
| Cron agent that makes a judgment call or needs reasoning | NO — keep as agent, but add retry logic or fallback model |
| Cron agent that pings an API and formats the result | YES — the ping + format is deterministic script work |
| Cron agent that writes findings to disk (consolidation, gap-finding) | YES — these are already scripts |

### Migration steps

1. Write the Python script with standalone logic (no agent needed)
2. Test it: `python3 ~/.hermes/scripts/<name>.py`
3. Update cron via `cronjob action='update' job_id='<id>' no_agent=True script='~/.hermes/scripts/<name>.py'`
4. Remove `prompt` and `skills` from the cron job — they're ignored when no_agent=True
5. Verify next tick: check `cronjob action='list'` for success

### For jobs that must remain agent-driven

- Set a per-job model override with a fallback provider
- Configure model timeout higher than 180s if the provider supports it
- The gateway's `request_kwargs.stream_timeout` in config.yaml controls the stale threshold

## Per-job model override pattern (Layer-1 external billing failures)

The Hermes config `fallback_providers` list exists, but the agent loop's retry path does NOT automatically consult it when the primary provider returns a billing-class error (e.g. `HTTP 402 Insufficient Balance`). Result: an agent-required cron job with no `model`/`provider` override inherits the config default, retries 3× against the exhausted provider, then errors out.

When this happens to a **monitoring or audit job**, the failure is recursive — the very tool that exists to surface the problem cannot fire because it is failing on the same problem. The watchdog catches it via the `CREDITS_ERROR` classifier, but the audit itself cannot report.

**Concrete fix (verified 2026-07-11 audit):**

For each agent-required cron job that does mission-critical monitoring/auditing, set per-job `model` and `provider` overrides pointing at a provider with known-good billing:

```json
// jobs.json
{
  "id": "85385abb646d",
  "name": "daily-strategist-audit",
  "no_agent": false,
  "model": "MiniMax-M3",
  "provider": "minimax"
}
```

After editing, verify the override took effect by manually running the script and grepping `agent.log` for the `provider=` field — it should show the override, not the original default.

**Audit-time diagnostic** (fire BEFORE writing any "system is healthy" claim):

```bash
# 1. Check for CREDITS_ERROR in the watchdog alerts
grep CREDITS_ERROR ~/.hermes/logs/alerts/watchdog.jsonl | tail -10

# 2. Cross-reference agent.log for the 402 pattern
grep "Insufficient Balance" ~/.hermes/logs/agent.log | tail -5

# 3. If both fire: surface to the user explicitly that the audit is flying blind.
#    Do NOT claim "0 alerts" when CREDITS_ERROR has fired in the same window.
```

**This applies specifically to `daily-strategist-audit` (85385abb646d), `morning-briefing` (3ec1c44b218f), and any other agent-required job that monitors system health.** No-agent jobs are unaffected.

## Current status (2026-06-18)

| Job | Type | Fix applied | Status |
|-----|------|-------------|--------|
| `hermes-config-auto-push` | Agent-driven (auto-push config to GitHub) | Convert to no-agent script | Pending |
| `uncommitted-watch` | Agent-driven (check git status across repos) | Convert to no-agent script | Pending |
| `idle-learning-run.sh` | no-agent script | `chmod +x` | Fixed ✅ |
| All others | no-agent scripts | N/A | Healthy ✅ |

## Audit-job blast-radius check (added 2026-07-11)

For any agent-required cron job whose failure would silently degrade monitoring (audit, briefing, watchdog, alerts), the structural fix is **per-job model/provider override, not relying on `fallback_providers` config**. Add the following 3-question check to cron-job creation:

1. **Is the job agent-required?** (`no_agent: false`)
2. **Does its failure hide a system-level problem?** (audit, briefing, watchdog-adjacent)
3. **Does jobs.json set explicit `model` + `provider`?** (otherwise it inherits config default — which may be the broken one)

If 1+2 are yes and 3 is no: **add the override before enabling the job**. This is a creation-time gate, not a runtime fix.

**Symptom to watch for:** watchdog alerts show `CREDITS_ERROR` for an agent-required monitoring job at the same time the job's `last_status` is `error` with a `RuntimeError` mentioning `Insufficient Balance`. The job is firing but failing on its own LLM call — exactly the recursive blind-spot pattern.