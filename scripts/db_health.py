#!/usr/bin/env python3
"""db_health.py — Database vacuum, TTL cleanup, backup, integrity check."""
import json, os, sqlite3, shutil, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERMES = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
BACKUP_DIR = HERMES / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

DBS = {
    "coordinator": HERMES / "coordinator.db",
    "state": HERMES / "state.db",
}

def check_integrity(db_path):
    if not db_path.is_file(): return {"healthy": True, "size_mb": 0, "integrity": "no file"}
    conn = sqlite3.connect(str(db_path), timeout=10)
    try:
        r = conn.execute("PRAGMA integrity_check").fetchone()
        size_mb = round(os.path.getsize(db_path) / 1024 / 1024, 1)
        conn.close()
        return {"healthy": r[0] == "ok", "size_mb": size_mb, "integrity": str(r[0])}
    except Exception as e:
        return {"healthy": False, "size_mb": 0, "error": str(e)[:100]}

def vacuum(db_path):
    if not db_path.is_file(): return {"vacuumed": False, "reason": "no file"}
    size_before = os.path.getsize(db_path)
    conn = sqlite3.connect(str(db_path), timeout=30)
    try:
        conn.execute("VACUUM")
        conn.close()
        size_after = os.path.getsize(db_path)
        return {"vacuumed": True, "before_mb": round(size_before/1024/1024,1),
                "after_mb": round(size_after/1024/1024,1),
                "saved_mb": round((size_before-size_after)/1024/1024,1)}
    except Exception as e:
        return {"vacuumed": False, "error": str(e)[:100]}

def backup(db_path, name):
    if not db_path.is_file(): return {"backed_up": False, "reason": "no file"}
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_DIR / f"{name}-{ts}.db"
    shutil.copy2(db_path, dest)
    # Compress
    import gzip
    with open(db_path, "rb") as src, gzip.open(str(dest) + ".gz", "wb") as dst:
        dst.write(src.read())
    dest.unlink()  # remove uncompressed
    # Keep only last 7 backups
    backups = sorted(BACKUP_DIR.glob(f"{name}-*.db.gz"))
    for old in backups[:-7]:
        old.unlink()
    return {"backed_up": True, "dest": str(dest) + ".gz"}

def cleanup_state_db():
    """Remove old sessions from state.db (TTL: 30 days)."""
    db = DBS["state"]
    if not db.is_file(): return {"cleaned": 0, "reason": "no file"}
    conn = sqlite3.connect(str(db), timeout=10)
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        # Try common session table names
        for table in ["sessions", "session", "conversations", "messages"]:
            try:
                r = conn.execute(f"DELETE FROM {table} WHERE updated_at < ? OR created_at < ?",
                                (cutoff, cutoff))
                deleted = r.rowcount
                if deleted > 0:
                    conn.commit()
                    return {"cleaned": deleted, "table": table}
            except: pass
        return {"cleaned": 0, "reason": "no matching tables or no old data"}
    except Exception as e:
        return {"cleaned": 0, "error": str(e)[:100]}
    finally:
        conn.close()

def run_all_checks():
    results = {}
    for name, path in DBS.items():
        results[name] = check_integrity(path)
    # Warn on large DBs
    warnings = []
    for name, r in results.items():
        if r.get("size_mb", 0) > 50:
            warnings.append(f"{name}: {r['size_mb']}MB — needs vacuum")
    return {"databases": results, "warnings": warnings}

def main():
    import argparse
    p = argparse.ArgumentParser(description="Database health manager")
    p.add_argument("--check", action="store_true"); p.add_argument("--vacuum", action="store_true")
    p.add_argument("--backup", action="store_true"); p.add_argument("--cleanup", action="store_true")
    p.add_argument("--all", action="store_true"); p.add_argument("--json", action="store_true")
    args = p.parse_args()
    result = {}
    if args.check or args.all: result = run_all_checks()
    if args.vacuum or args.all:
        result["vacuum"] = {n: vacuum(p) for n, p in DBS.items()}
    if args.backup or args.all:
        result["backup"] = {n: backup(p, n) for n, p in DBS.items()}
    if args.cleanup or args.all:
        result["cleanup"] = cleanup_state_db()
    if args.json: print(json.dumps(result, indent=2, default=str))
    else:
        for k, v in result.items():
            if isinstance(v, dict):
                print(f"{k}: {json.dumps(v, default=str)[:200]}")
            else:
                print(f"{k}: {v}")

if __name__ == "__main__": main()
