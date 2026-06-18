#!/usr/bin/env python3
"""Alert Resolution System — closes the loop on every open alert.

HOW IT WORKS:
  The watchdog and probes write alerts to watchdog.jsonl with no lifecycle tracking.
  This script is called at the END of every watchdog/probe run. It:
    1. Reads ALL existing alerts from watchdog.jsonl
    2. Compares current (just-detected) issues against open alerts
    3. Marks as "resolved" any open alert that did NOT fire this run
    4. Appends a resolution entry so the audit trail is complete

  Alerts have a lifecycle:
    CREATE  → {type, message, status: "open", timestamp}
    RESOLVE → {type, message, status: "resolved", resolved_at, resolution: "condition_cleared"}

  A resolved alert stays in the log permanently — never deleted. The strategist
  audit reads status=open vs status=resolved to compute health trends.

USAGE:
  python3 alert-resolver.py --check '["CRON_ERROR: foo failed", "GIT_DIRTY: 12 files"]'

  The --check flag takes the CURRENT run's alert list as JSON. The resolver compares
  this against open alerts and marks resolutions.

DESIGN PRINCIPLES:
  - Never delete or modify existing entries (append-only log)
  - A resolved alert can re-open if the same condition fires again
  - Silently skips entries that already have a status field
"""

import json
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
ALERT_LOG = HERMES_HOME / "logs" / "alerts" / "watchdog.jsonl"
PROBE_LOG = HERMES_HOME / "logs" / "maintenance" / "probe-findings.jsonl"
POLICY_LOG = HERMES_HOME / "logs" / "policy-firings.jsonl"

def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def read_alerts() -> list[dict]:
    """Read all entries from the alert log. Returns empty list if file missing."""
    if not ALERT_LOG.exists():
        return []
    entries = []
    try:
        with open(ALERT_LOG) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return entries

def extract_current_alert_ids(current_alerts: list[str]) -> set[str]:
    """Extract canonical alert 'fingerprint' from just-checked alert messages.
    
    The watchdog uses type-prefixed strings like 'CRON_ERROR: foo errored: ...'
    We canonicalize by stripping timestamps and truncating variable parts.
    """
    ids = set()
    for a in current_alerts:
        # Use the full message as the canonical key (excluding timestamps inside messages)
        ids.add(a.strip())
    return ids

def find_open_alert_entries(entries: list[dict]) -> tuple[list[dict], list[int]]:
    """Find alert entries that are currently open (no status or status='open').
    
    Returns:
        - List of open alert entries
        - List of their indices in the original entries list
    """
    open_entries = []
    open_indices = []
    for i, e in enumerate(entries):
        # Only individual alert entries (not summaries, not already resolved)
        e_type = e.get("type", "")
        if e_type == "watchdog_summary":
            continue
        if e.get("status") == "resolved":
            continue
        # Must have a 'message' field
        if "message" not in e:
            continue
        # Must have a 'type' field other than empty
        if not e_type:
            continue
        open_entries.append(e)
        open_indices.append(i)
    return open_entries, open_indices

def resolve_alert(entry_index: int, original_entries: list[dict]) -> None:
    """Append a resolution entry for the alert at entry_index.
    
    We don't modify the original entry (append-only). We write a companion
    entry with the same message but status=resolved + resolved_at.
    """
    original = original_entries[entry_index]
    resolution = {
        "timestamp": iso_now(),
        "type": original.get("type", "UNKNOWN"),
        "message": original.get("message", ""),
        "status": "resolved",
        "resolved_at": iso_now(),
        "resolution": "condition_cleared",
        "open_since": original.get("timestamp", "unknown"),
        "healthy": True,
    }
    with open(ALERT_LOG, "a") as f:
        f.write(json.dumps(resolution) + "\n")

def main() -> int:
    import argparse
    
    parser = argparse.ArgumentParser(description="Close the loop on alerts")
    parser.add_argument("--check", required=True,
                        help="JSON list of current-run alert strings: "
                             "e.g. '[\"CRON_ERROR: foo\", \"GIT_DIRTY: 12 files\"]'")
    parser.add_argument("--verbose", action="store_true",
                        help="Print resolution actions for audit")
    args = parser.parse_args()
    
    # Parse current alerts
    try:
        current_alerts: list[str] = json.loads(args.check)
    except json.JSONDecodeError as e:
        print(f"alert-resolver: ERROR parsing --check arg: {e}", file=sys.stderr)
        return 1
    
    current_ids = extract_current_alert_ids(current_alerts)
    
    # Read existing alert log
    entries = read_alerts()
    open_entries, open_indices = find_open_alert_entries(entries)
    
    # Build set of currently-open alert messages
    open_messages = set()
    for e in open_entries:
        msg = e.get("message", "").strip()
        if msg:
            open_messages.add(msg)
    
    # Find alerts that are open but NOT in the current run = conditions cleared
    resolved_count = 0
    for msg in sorted(open_messages):
        if msg not in current_ids:
            # This alert was open but its condition no longer exists
            # Find all entries matching this message and resolve the LATEST open one
            for i in reversed(open_indices):
                e = entries[i]
                if e.get("message", "").strip() == msg and e.get("status") != "resolved":
                    resolve_alert(i, entries)
                    resolved_count += 1
                    break
    
    # Also handle the reverse: alerts that fired but already have an OPEN entry
    # (We don't re-create them — the existing open entry is correct)
    new_count = 0
    for msg in sorted(current_ids):
        if msg not in open_messages:
            new_count += 1
    
    if args.verbose or resolved_count > 0:
        if resolved_count:
            print(f"🔄 alert-resolver: resolved {resolved_count} alert(s)")
        if new_count:
            print(f"   {new_count} new alert(s) this run (logged by caller)")
    
    # ── Phase 2: Resolve stale probe findings ───────────────────────────────
    # Probe findings have no status field. We mark entries as resolved by
    # appending a companion entry with status=resolved. The strategist audit
    # reads status=open vs status=resolved.
    if PROBE_LOG.exists():
        try:
            p_entries = []
            with open(PROBE_LOG) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            p_entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
            
            # Find probe findings that are still open (no status field)
            open_probes = [e for e in p_entries if e.get("status") != "resolved"]
            # Check if a probe finding's condition has cleared (gateway)
            # Current gateway status — if running, all gateway probe findings resolve
            import subprocess
            gw_check = subprocess.run(
                "ps aux | grep hermes_cli.main.gateway | grep -v grep | wc -l",
                shell=True, capture_output=True, text=True, timeout=5
            )
            gw_running = gw_check.stdout.strip() and int(gw_check.stdout.strip()) > 0
            
            resolved_probes = 0
            for e in open_probes:
                should_resolve = False
                trigger = e.get("trigger", "")
                if gw_running and "Gateway" in trigger:
                    should_resolve = True
                
                if should_resolve:
                    resolution = {
                        "source": "probe",
                        "domain": e.get("domain", ""),
                        "trigger": trigger,
                        "fix": e.get("fix", ""),
                        "status": "resolved",
                        "resolved_at": iso_now(),
                        "added_at": e.get("added_at", ""),
                    }
                    with open(PROBE_LOG, "a") as f:
                        f.write(json.dumps(resolution) + "\n")
                    resolved_probes += 1
            
            if args.verbose and resolved_probes:
                print(f"🔄 alert-resolver: resolved {resolved_probes} probe finding(s)")
                
        except (OSError, json.JSONDecodeError) as e:
            if args.verbose:
                print(f"  alert-resolver: probe log error: {e}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
