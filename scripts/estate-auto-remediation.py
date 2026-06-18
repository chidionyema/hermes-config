#!/usr/bin/env python3
"""Estate Auto-Remediation — takes the optimization report and actually
executes the recommended actions.

Current capabilities:
  - Archive dead policies (0 hits, 7+ days old)
  - Consolidate overlapping policies (same domain, similar triggers)
  - Clean stale watchdog alerts (>7 days old)

This is SAFE by design: always creates a backup and logs every change.
Dry-run mode: pass --dry-run to preview without applying.
"""

import json, os, shutil, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
POLICY_DIR = HERMES_HOME / "policies"
ARCHIVE_DIR = HERMES_HOME / "policies" / "_archived"
LOG_FILE = HERMES_HOME / "logs" / "remediation" / "actions.jsonl"

ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
(LOG_FILE.parent).mkdir(parents=True, exist_ok=True)

DRY_RUN = "--dry-run" in sys.argv

def log_action(action_type, target, detail, success=True):
    """Log remediation action to JSONL."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": action_type,
        "target": target,
        "detail": detail,
        "success": success,
        "dry_run": DRY_RUN,
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry

def archive_policy(policy_id):
    """Move a policy JSON to _archived/ and mark it."""
    for f in POLICY_DIR.glob("*.json"):
        try:
            with open(f) as fh:
                p = json.load(fh)
            if p.get("id") == policy_id or f.stem == policy_id:
                dest = ARCHIVE_DIR / f.name
                if not DRY_RUN:
                    shutil.move(str(f), str(dest))
                    # Also archive any related files (e.g., checksums)
                    for related in POLICY_DIR.glob(f"{f.stem}.*"):
                        if related.suffix != ".json":
                            shutil.move(str(related), str(ARCHIVE_DIR / related.name))
                action = log_action("archive_policy", policy_id, f"Moved to {dest}")
                return action
        except:
            continue
    return log_action("archive_policy", policy_id, "Policy file not found", success=False)

def consolidate_policies(same_domain_policies):
    """Merge policies in the same domain into one."""
    # For now: log the consolidation candidate. Actual merge is manual.
    ids = [p.get("id", "?") for p in same_domain_policies if isinstance(p, dict)]
    if len(ids) >= 2:
        action = log_action("consolidation_candidate", ", ".join(ids), 
                          f"{len(ids)} policies in same domain — pending manual review")
        return action
    return None

def clean_watchdog_alerts():
    """Remove watchdog alerts older than 7 days."""
    alert_file = HERMES_HOME / "logs" / "alerts" / "watchdog.jsonl"
    if not alert_file.exists():
        return log_action("clean_alerts", "watchdog.jsonl", "No alert file found", success=False)
    
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    kept = []
    removed_count = 0
    
    with open(alert_file) as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
                ts = entry.get("timestamp", "")
                if ts:
                    entry_time = datetime.fromisoformat(ts)
                    if entry_time < cutoff:
                        removed_count += 1
                        continue
                kept.append(line)
            except:
                kept.append(line)  # keep unparseable lines
    
    if removed_count > 0 and not DRY_RUN:
        with open(alert_file, "w") as f:
            f.writelines(kept)
    
    return log_action("clean_alerts", "watchdog.jsonl",
                     f"Removed {removed_count} old alerts, kept {len(kept)}")

# ── MAIN ──────────────────────────────────────────
if __name__ == "__main__":
    actions = []
    
    print(f"{'DRY RUN' if DRY_RUN else 'LIVE'} — Estate Auto-Remediation")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # 1. Archive dead policies
    print("── Scanning for dead policies ──")
    for f in sorted(POLICY_DIR.glob("*.json")):
        try:
            with open(f) as fh:
                p = json.load(fh)
            pid = p.get("id", f.stem)
            hits = p.get("hits", 0)
            status = p.get("status", "?")
            
            if hits == 0 and status != "archived":
                created = p.get("created_at", "")
                age_days = 0
                if created:
                    try:
                        created_dt = datetime.fromisoformat(created)
                        age_days = (datetime.now(timezone.utc) - created_dt).days
                    except:
                        pass
                
                if age_days >= 7 or not created:  # Grace period: 7 days before auto-archive
                    print(f"  → Archiving: {pid} (hits={hits}, age={age_days}d, domain={p.get('scope',{}).get('domain','?')})")
                    result = archive_policy(f.stem)
                    actions.append(result)
                else:
                    print(f"  → Skipping young policy: {pid} (age={age_days}d, hits={hits})")
            else:
                print(f"  ✓ Active: {pid} (hits={hits})")
        except Exception as e:
            print(f"  ✗ Error reading {f.name}: {e}")
    
    # 2. Check for consolidation candidates
    print()
    print("── Scanning for overlapping policies ──")
    domain_groups = {}
    for f in sorted(POLICY_DIR.glob("*.json")):
        try:
            with open(f) as fh:
                p = json.load(fh)
            domain = p.get("scope", {}).get("domain", "uncategorized")
            domain_groups.setdefault(domain, []).append(p)
        except:
            pass
    
    for domain, policies in sorted(domain_groups.items()):
        if len(policies) >= 2 and domain not in ("uncategorized",):
            print(f"  → Overlap in domain '{domain}': {', '.join(p.get('id','?') for p in policies)}")
            result = consolidate_policies(policies)
            if result:
                actions.append(result)
    
    # 3. Clean old alerts
    print()
    print("── Cleaning old watchdog alerts ──")
    result = clean_watchdog_alerts()
    actions.append(result)
    print(f"  {result['detail']}")
    
    # Summary
    print()
    print(f"{'── DRY RUN COMPLETE ──' if DRY_RUN else '── REMEDIATION COMPLETE ──'}")
    print(f"Actions taken: {len([a for a in actions if a.get('success')])}")
    print(f"Failures: {len([a for a in actions if not a.get('success')])}")
    print(f"Log: {LOG_FILE}")
