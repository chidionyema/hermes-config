# Prospector Config Co-Dependencies

## batch_size + tick deadline

These two values are coupled. Changing one without the other causes silent failure.

### The coupling

| File | Key | Default | Unit |
|------|-----|---------|------|
| `config.yaml` | `schedule.batch_size` | 5 (was 15 as of 2026-07-31) | candidates per tick |
| `prospector/scheduler/run_scheduled.py` | `_TICK_HARD_DEADLINE_S` | 10800 (env: `PROSPECTOR_TICK_DEADLINE_S`) | seconds |

### The rule

```
batch_size * per_candidate_minutes * 60 < _TICK_HARD_DEADLINE_S * 0.8
```

Measured 2026-07-02: claude_cli chain ≈ 10 min/candidate. cursor_cli primary (2026-07-31) should be faster, but budget conservatively.

### Failure mode: deadline too tight

**Symptom:** Daemon runs, dossiers survive (stored to disk), but tick rows and diagnostics are lost. Tick finishes with "Force-exited" error. Zero tick rows in `ticks.jsonl`.

**Root cause:** `_TICK_HARD_DEADLINE_S` fires before the batch completes. The force-exit handler writes a tick with error but the main thread is hung, so bookkeeping may fail. Launchd relaunches the daemon, which tries again with the same batch size, hits the same deadline, force-exits again — relaunch livelock.

**Proven live 2026-07-02:** `batch_size=20` + `_TICK_HARD_DEADLINE_S=2700` (45 min) meant NO tick ever completed. 20 × 10 min = 200 min needed, deadline was 45 min.

### Historical values

| Date | batch_size | deadline | rationale |
|------|-----------|----------|-----------|
| 2026-07-02 | 20 → 5 | 2700 → 4500 | Livelock fix: batch was 20, deadline 45min, nothing completed |
| 2026-07-31 | 5 → 15 | 4500 → 10800 | Founder directive: batch_size=15. cursor_cli is primary (faster than claude_cli). exa in grounding chain reduces wall time. Budgeted 3h conservatively. |

### Checklist when changing batch_size

1. Update `config.yaml` `schedule.batch_size`
2. Update `run_scheduled.py` `_TICK_HARD_DEADLINE_S` default (or set `PROSPECTOR_TICK_DEADLINE_S` env var)
3. Restart daemon: `launchctl kickstart -k gui/501/com.prospector.scheduler`
4. Monitor first tick: check `ticks.jsonl` for completion (not force-exit error)
5. Check `heartbeat.json`: phase should transition generating → idle (not stuck at generating)
