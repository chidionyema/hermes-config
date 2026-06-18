# Estate Pipeline Architecture

## Data Flow

```
estate-inventory.py ──────────────────────────────┐
       │ (raw snapshot + report)                    │
       ▼                                            │
estate-drift-detector.py                             │
       │ (compares to last JSON snapshot)            │
       │ (writes drift report only if changed)       │
       ▼                                            │
estate-optimization-scanner.py ◄────── reads ───────┘
       │ reads: bottleneck reports, near-miss,       │
       │ trend analysis, watchdog alerts,            │
       │ policy firings, drift report                │
       │ produces: ranked recommendations            │
       ▼                                            │
estate-auto-remediation.py ◄─────────────────────────┘
       │ (dry-run only: applies optimization recs)  │
       ▼                                            │
  Output to Telegram (via cron delivery)             │
                                                     │
  All phases also write files:                        │
    reports/estate-inventory.md                       │
    reports/estate-drift.md (conditional)             │
    reports/estate-optimization.md                    │
    logs/remediation/actions.jsonl                    │
```

## File Dependencies

| Phase | Reads | Writes |
|---|---|---|
| Inventory | filesystem | `reports/estate-inventory.md` |
| Drift | filesystem, `reports/snapshots/estate-*.json` | `reports/estate-drift.md`, new snapshot |
| Optimization | `logs/meta-improver/bottleneck-*.json`, `logs/maintenance/near-miss-*.json`, `logs/trends/trend-*.json`, `logs/alerts/watchdog.jsonl`, `logs/policy-firings.jsonl`, `reports/estate-drift.md` | `reports/estate-optimization.md` |
| Remediation | `policies/*.json`, `logs/alerts/watchdog.jsonl` | `policies/_archived/*`, `logs/remediation/actions.jsonl` |

## Snapshot Rotation

Snapshots live in `reports/snapshots/estate-*.json`. Only the most recent is used for comparison. Old snapshots accumulate — no cleanup logic yet. If disk usage becomes an issue, add retention: keep last 30, archive older.

## Safety Properties

1. **Read-only phases 1-3** — inventory, drift, and optimization never modify state
2. **Phase 4 is dry-run-only** — explicitly guarded: `--dry-run` prints actions without executing
3. **Backup before archive** — auto-remediation `shutil.move` preserves files; nothing is deleted
4. **7-day grace** — policies must be 7+ days old with 0 hits before archival is considered
5. **Log-before-act** — every remediation action is logged to JSONL before execution

## Cron Delivery Behavior

The cron script `estate-full-run.sh` prints all output to stdout. Since `no_agent=true`, stdout is delivered verbatim as the Telegram message. This means:
- Drift and optimization reports appear inline in the same message
- If drift is empty (no change), the drift section just says "No drift detected"
- The full output can be long (~200 lines) — consider truncation at Telegram's 4096-char limit
