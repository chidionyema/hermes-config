# Probe Contract — Every Health Probe, Watchdog, and Verification Script

Distilled from the 2026-06-18 audit and the cron probes Claude built that session. Every probe-style script in Otto's estate must implement this contract. A probe that violates it is itself a bug.

## The 6 Required Properties

| # | Property | Why it matters | Implementation |
|---|---|---|---|
| 1 | **Declared budget** | Caller and cron know what to expect | Top-of-file: `BUDGET_SECONDS = 90` (or whatever fits) |
| 2 | **Timeout = budget × 2** | Safety margin; tight enough to fail fast, loose enough to allow GC pauses / first-time imports | `TIMEOUT = BUDGET_SECONDS * 2` |
| 3 | **Heartbeat on fixed cadence** | Distinguishes "running slow" from "hung" | Every `BUDGET/3` seconds, write PID + timestamp to `~/.hermes/state/<probe>.heartbeat` |
| 4 | **Final state file** | The probe's verdict survives cron output truncation | Write `~/.hermes/state/<probe>.json` with `{exit_code, duration_ms, state, last_change, fingerprint}` on every run |
| 5 | **Silent when state unchanged** | "Healthy" is the default; alerts are signal, not noise | Compare current state to previous state file; emit output only on change |
| 6 | **One alert on state change** | The user sees deltas, not noise | Use canonical fingerprint (hermes_fingerprint.py) to dedup; emit exactly one message per state transition |

## The Anti-Patterns (real production hits from 2026-06-18)

- **No timeout declared** — probe runs forever, cron kills it at 120s, the user gets a "script timed out" raw alert. *(repo-health-check.py: 3 repos × 120s worst case = 360s, cron cap 120s.)*
- **Exit 0 unconditionally** — watchdog.sh exits 0 no matter what, so jobs.json.last_status stays "ok" and the watchdog can never see its own failure. *(The watchdog hiding the watchdog.)*
- **Resolve by message-absence** — alert-resolver.py marks an alert "resolved" if its message string is absent from the current run. PID-varying restart messages guarantee false "cleared" status. *(The resolver hiding the resolver's failures.)*
- **No heartbeat** — hung probe is indistinguishable from dead probe. *(The signal-engine-daemon-watchdog bug: no way to tell "daemon hung" from "daemon died cleanly".)*
- **Self-certifying probe** — probe writes a "PASS" line, then a human or Otto reads the line and reports "all green." The probe must be its own verifier: the state file is the receipt, the cron output is the diff.

## Template

```python
#!/usr/bin/env python3
"""Probe: <name>. Implements the probe contract.
Reference: ~/.hermes/skills/otto-operating-model/references/probe-contract.md
"""
import json, os, time
from pathlib import Path

BUDGET_SECONDS = 90
TIMEOUT = BUDGET_SECONDS * 2
HEARTBEAT_EVERY = BUDGET_SECONDS // 3
STATE_FILE = Path.home() / ".hermes" / "state" / "<name>.json"
HEARTBEAT_FILE = Path.home() / ".hermes" / "state" / "<name>.heartbeat"

def heartbeat():
    HEARTBEAT_FILE.write_text(f"{os.getpid()}\t{time.time()}\n")

def read_previous_state():
    if not STATE_FILE.exists():
        return None
    return json.loads(STATE_FILE.read_text())

def write_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))

def main() -> int:
    start = time.monotonic()
    heartbeat()
    # ... do the actual check ...
    current_state = {"exit_code": 0, "duration_ms": int((time.monotonic()-start)*1000), "fingerprint": "<canonical>", "state": "<verdict>"}
    previous = read_previous_state()
    if previous and previous.get("fingerprint") == current_state["fingerprint"]:
        return 0  # silent when state unchanged
    write_state(current_state)
    print(f"<one-line state change>")  # emitted only on change
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

## Verification

Every probe must be runnable in isolation. The probe's own test asserts:
1. Empty state file → produces nothing on second run (silent)
2. Heartbeat file is written and updated
3. State file is updated with the verdict
4. Timeout fires at exactly `BUDGET_SECONDS * 2` if the check hangs

## The Meta-Probe (the watchdog for the watchdogs)

A separate probe that scans `~/.hermes/state/*.heartbeat` and `~/.hermes/state/*.json` and fires if:
- A heartbeat is older than `BUDGET_SECONDS * 2` (probe is hung)
- A state file is older than 24h for a probe that should run hourly (probe is dead)
- A state file's fingerprint contradicts its exit_code (probe is lying)
- Two probes have mutually-exclusive states that should agree (probe is contradictory)

This is the dropped-ball watchdog for the probe layer. Build it.
