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

## Current status (2026-06-18)

| Job | Type | Fix applied | Status |
|-----|------|-------------|--------|
| `hermes-config-auto-push` | Agent-driven (auto-push config to GitHub) | Convert to no-agent script | Pending |
| `uncommitted-watch` | Agent-driven (check git status across repos) | Convert to no-agent script | Pending |
| `idle-learning-run.sh` | no-agent script | `chmod +x` | Fixed ✅ |
| All others | no-agent scripts | N/A | Healthy ✅ |
