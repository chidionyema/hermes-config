# Self-Audit Methodology

A reproducible pattern for running a comprehensive system audit, identifying issues, batching fixes, and proving everything works.

## Trigger conditions
Run this when:
- Chidi says "audit yourself", "self audit", "comprehensive audit"
- After significant system changes (new skills, scripts, cron jobs, policies)
- Before reporting system health or delivering a status summary
- When you suspect drift between what's supposed to be running and what's actually running

## Protocol

### Phase 1: Gather (execute_code batch)
Use `execute_code` (not terminal) to batch ALL diagnostic commands into a single script. This gives you structured dict output instead of parsing terminal strings.

```python
from hermes_tools import terminal

# Batch ALL checks into parallel calls
results = {}
r = terminal("launchctl list | grep -i hermes")
results['gateway'] = r['output'].strip()
r = terminal("test -f ~/.hermes/meta/OFF_SWITCH && echo PRESENT || echo MISSING")
results['off_switch'] = r['output'].strip()
# ... etc
```

Check these dimensions:
1. **Process health** — gateway PID, launchd KeepAlive, uptime
2. **Souls contract** — OFF_SWITCH, SHA-256 hash match, rollback snapshots
3. **Pipeline health** — every script in the idle pipeline runs (not just exists)
4. **Cron health** — last_status for every job, missing scripts, never-run jobs
5. **Policy health** — every policy status, hits, conflicts, vague scope
6. **Memory pressure** — MEMORY.md size vs 2200-char limit
7. **Git state** — uncommitted files count
8. **Config integrity** — fallback providers, auth pool, model config

### Phase 2: Identify issues
Classify each finding:
- **🔴 Critical** — will cause a failure (script has no main, cron crashes, policy has 0 matches, memory full)
- **🟡 Warning** — potential problem (no fallback, duplicate policies, orphan scripts, never-run crons)
- **🟢 Healthy** — working correctly, note for completeness

Trace each 🔴 to root cause. Ask: "what would actually break, and why?"

### Phase 3: Apply fixes (batch via execute_code)
Use `execute_code` to apply multiple fixes in a single script. Prefer:
- `patch()` for SKILL.md/code edits
- `write_file()` for new scripts
- `terminal()` for hermes config commands
- `terminal("git add -A && git commit...")` for version control

Don't fix one thing at a time. Batch them. Include verification in the same script.

### Phase 4: Verify (comprehensive loop)
Run ALL checks again in a single verification loop. Output as a table:

```
| # | Fix | Before | After | Evidence |
|---|-----|--------|-------|----------|
| 1 | X   | broken | fixed | cmd output |
```

Each verification must include a command that EXERCISES the fix — not just checks that a file exists.

### Phase 5: Push to git
```bash
cd ~/.hermes && git add -A && git commit -m 'audit fixes: <summary>' && git push origin main
```

This ensures all fixes land as a single coherent change, not scattered commits.

## Key principles
- **Fix first, prove second:** apply all fixes before reporting — the report IS the proof
- **No intermediate reports:** don't say "fixing X... done, fixing Y..." — batch, verify, report
- **Prefer execute_code over terminal** for batching multiple operations (structured output, one context window slot)
- **If the same issue appears in multiple sessions, escalate to structural fix** (gate, script, cron) — not another policy or memory entry
- **Every 🔴 fix must have a ✅ verification** — if you can't verify it, you didn't fix it
