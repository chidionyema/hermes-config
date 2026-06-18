# Alert Resolution Lifecycle

## The Core Pattern

Every alert has a lifecycle:

```
CREATE → {status: "open", timestamp, type, message}
RESOLVE → {status: "resolved", resolved_at, resolution: "condition_cleared"}
```

Alerts are **never deleted or mutated**. Resolution is a companion entry appended to the same log. The strategist audit reads `status=open` vs `status=resolved` for health trends.

## Files Involved

| File | Purpose | Schema |
|---|---|---|
| `~/.hermes/logs/alerts/watchdog.jsonl` | System alerts (cron, git, gateway, disk) | `{type, message, status?, healthy}` |
| `~/.hermes/logs/maintenance/probe-findings.jsonl` | Probe findings (gateway down) | `{source, domain, trigger, fix, status?, added_at}` |
| `~/.hermes/scripts/alert-resolver.py` | Resolver script | See below |

## Resolver Logic

```python
# Called with current run's alert list as JSON:
python3 alert-resolver.py --check '["CRON_ERROR: foo", "GIT_DIRTY: 12"]'

# Phase 1: Watchdog alerts
#   - Read all watchdog.jsonl entries
#   - Find entries with status != "resolved" that have a type + message
#   - Compare message against --check list
#   - If message NOT in --check list → condition cleared → append resolution entry

# Phase 2: Probe findings
#   - Read all probe-findings.jsonl entries
#   - Find entries with status != "resolved"
#   - If gateway is running and trigger contains "Gateway" → resolve
```

## Known Gateway Bug (Fixed 2026-06-18)

The watchdog's `check_gateway()` had a regex bug for months. The grep pattern was:

```python
ps aux | grep 'hermes_cli.main gateway'  # space separator — NEVER matched
```

But the actual process is:

```
python -m hermes_cli.main.gateway run  # dot separators
```

**Result:** Gateway was always reported as DOWN even though it was running. This caused 54 GATEWAY_DOWN / GATEWAY_IDLE alerts to accumulate in the log with no possibility of resolution.

**Fix:** Changed to:

```python
ps aux | grep 'python.*gateway'  # matches both forms
```

## History

- Pre-2026-06-18: alerts written with no `status` field. Append-only, no resolution tracking. 15 watchdog alerts + 6 probe findings accumulated with 0 resolved.
- 2026-06-18: `alert-resolver.py` created. watchdog.py patched to write `status: "open"` + call resolver. improvement-probe.sh patched for silence when healthy. Gateway regex fixed. 54 alerts resolved, 0 open.
