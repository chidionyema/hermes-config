# Output Dedup & State Mirroring Patterns

Two related patterns for fixing "log noise" / "structurally-identical file" classes of bug in cron-driven Otto subsystems. Both are class-level techniques — applicable to any script that emits state to disk on a cadence.

## Pattern 1: Hash-before-write dedup for periodic JSON dumps

**Symptom:** A cron script (e.g. `near-miss-analyzer.py`, `gap-finding.py`, `trend-analyzer.py`) runs every 15-30 min and writes a new JSON file each time. The structural content is stable across runs (same untriggered policies, same co-firing contexts, same domain gaps). Only the `generated_at` timestamp and a count field change. Result: hundreds of byte-identical files per day, ~280KB of duplicate data, and the trend analyzer's "persistently untriggered" count inflates to 200+ on policies that are correctly firing as conceptual gates.

**The fix:** Hash the stable structural content before writing. Skip the write if the hash matches the previous run. Cache the hash on disk next to the output directory.

**Code template** (drop into any periodic-JSON-dump script):

```python
import hashlib as _hl
import json
from pathlib import Path

OUTPUT_DIR = Path("/path/to/output")

# At the end of main(), before writing findings:
stable_keys = ("untriggered_policies", "co_firing_contexts", "domain_coverage_gaps")
stable_payload = {k: findings.get(k, []) for k in stable_keys}
stable_hash = _hl.md5(json.dumps(stable_payload, sort_keys=True).encode()).hexdigest()

hash_cache = OUTPUT_DIR / "_stable_hash"
prev_hash = hash_cache.read_text().strip() if hash_cache.exists() else ""

if prev_hash == stable_hash:
    # Silent — same structural content as last run, nothing new to record
    print(f"unchanged (stable_hash={stable_hash[:8]}, skipping write)")
    return 0

# Normal write path
report_path = OUTPUT_DIR / f"prefix-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
with open(report_path, "w") as f:
    json.dump(findings, f, indent=2)
hash_cache.write_text(stable_hash)
```

**Why this works:**
- The hash is over the **stable structural content only** — explicitly exclude volatile fields like `generated_at`, `total_firings`, `current_count`, etc.
- If any structural content actually changes (e.g. a new untriggered policy appears), the hash differs and a new file is written. Real signal still surfaces.
- If nothing changes, the script is silent — no write, no new file. The trend analyzer stops seeing inflation.
- The cache file (`_stable_hash`) is just a single hex string. Trivial to inspect.

**Verification (two back-to-back runs):**
```
Run 1: 📊 Near-Miss Analysis saved to logs/maintenance/near-miss-20260703-080707.json
Run 2: 📊 Near-Miss Analysis unchanged (stable_hash=ae585b07, skipping write)
```

**When to apply this pattern:**
- Script runs on a fixed cadence (every 15m / 30m / hourly) AND
- Output is a timestamped JSON file in a directory AND
- The structural content is mostly stable (few changes per day)

**When NOT to apply:**
- Output is meant to be append-only history (use JSONL instead)
- Structural content is highly variable (hash dedup buys nothing)
- Output is consumed by tools that expect a file per tick (e.g. a dashboard that lists files by mtime)

**Alternative pattern (not used here):** switch to append-only JSONL (`near-miss-log.jsonl`) — one line per scan, no timestamped file proliferation. This works when you want a continuous history; the hash dedup is better when you want "current state" semantics with no history.

## Pattern 2: State file vs log file — keep them in sync

**Symptom:** A subsystem (e.g. `watchdog.py`) maintains truth in a **state file** (`watchdog-state.json`) keyed by fingerprints, with a `del` operation that drops resolved fingerprints from the state. It also writes a **log file** (`watchdog.jsonl`) with one entry per detection: `{"type": "CRON_ERROR", "status": "open", ...}`. When the state file drops a fingerprint (resolved after K clean runs), the log file does NOT get a matching `{"status": "resolved"}` line. Result: `grep '"status": "open"' logs/alerts/watchdog.jsonl` returns 20 historical entries while the state file has 0 active fingerprints. Every audit (and the daily strategist cron) has to remember to cross-check the state file before trusting the log.

**The fix:** When the state file drops a fingerprint, append a matching `{"status": "resolved", "resolved_at": ..., "resolution": "K_runs_clean", "verifier": "..."}` line to the log file. This way the log is a complete history that mirrors the state file's truth, and grep-based queries return only currently-open alerts.

**Code template** (drop into the state-resolution block):

```python
# Existing: drop resolved fingerprint from state
for fp in resolved_fps:
    del fps[fp]

# Add: append a status: resolved line to the log file
for fp in resolved_fps:
    try:
        rec = old_state_fps.get(fp, {})  # capture before del
        resolution_entry = {
            "timestamp": iso_now(),
            "type": rec.get("type", "UNKNOWN"),
            "message": rec.get("sample", ""),
            "fingerprint": fp,
            "status": "resolved",
            "resolved_at": iso_now(),
            "resolution": "K_runs_clean",  # or "probe_verified", "manual", etc.
            "verifier": "auto_resolver",    # or your verifier name
            "open_since": rec.get("first_seen"),
            "healthy": True,
        }
        with open(ALERT_LOG, "a") as _f:
            _f.write(json.dumps(resolution_entry) + "\n")
    except Exception:
        pass
```

**Why this matters:**
- Grep-based audits (which the user runs frequently) get accurate results without cross-checking state.
- The log becomes a true lifecycle record: open → ... → resolved, with timestamps.
- Operators can answer "when did this alert first appear and when did it resolve?" from the log alone.
- State file remains the source of truth for the live daemon; log is the historical record. They agree.

**When to apply this pattern:**
- Any subsystem that maintains a state file (fingerprints, deduplication sets, in-progress queues) AND
- Also writes a log file with one entry per state change AND
- State changes can happen without a corresponding log entry (resolutions, drops, expirations)

**Verification probe:**
```bash
# After fix: count of open and resolved should match the state file
grep -c '"status": "open"' logs/alerts/watchdog.jsonl | tail -1
grep -c '"status": "resolved"' logs/alerts/watchdog.jsonl | tail -1
python3 -c "import json; d=json.load(open('logs/alerts/watchdog-state.json')); print(f'live fingerprints: {len(d.get(\"fingerprints\", {}))}')"
```

**Known false-positive pattern (still open as of 2026-07-03):** the `watchdog.py` state-based resolution works correctly — `open_fingerprints: 0` matches the empty state file. The log file just doesn't mirror it. Fix not yet applied (P3 carry-over); pattern documented here for the next audit.

## Related patterns

- **Append-only history** (`logs/.../something.jsonl`) when you want every event, never deduplicated. Combine with `tail -1` for "current state."
- **Snapshot with diff** (`meta-improver.py --preflight / --postflight`) when you want periodic state snapshots with deltas. Don't try to dedup — the deltas are the signal.
- **Capped history** (`rotation: keep last N`) when the file is meant to be a rolling buffer. The dedup pattern above would silently destroy this — only apply hash dedup when you genuinely want "current state" semantics.

## Pitfalls (real production hits)

1. **Hashing the wrong fields.** If you include `generated_at` in the hash, every run produces a different hash → dedup is a no-op. If you exclude the *wrong* stable field (e.g. `untriggered_policies`), a real change doesn't trigger a write. Audit the payload explicitly before committing to the stable_keys list.
2. **Cache file in a write-restricted directory.** The `_stable_hash` file needs write permission. If `OUTPUT_DIR` is read-only or sandboxed, the dedup silently fails (hash always reads as empty, every run writes). Add a try/except with a clear error message.
3. **Forgetting to seed the cache on first run.** The first run always writes (prev_hash is empty). That's correct. The second run is the one that skips. Don't expect "first run skips" — that's a bug.
4. **Mixing state-file truth with log-file derivations.** If both the state file and the log claim to be authoritative for "what's currently open," they'll drift. Pick one. The state file is for the live daemon; the log is for the historical record; the log MUST mirror the state file's drops, or the next grep will mislead an audit.
5. **Don't dedup the audit-trail.jsonl.** That log is meant to be append-only history. Hash-dedup would destroy the audit trail. The pattern is for periodic state snapshots, not event logs.
