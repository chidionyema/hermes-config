#!/usr/bin/env python3
import os
import sys
import json
import time
import hmac
import hashlib
import sqlite3
import subprocess

HERMES = os.path.expanduser("~/.hermes")
DB_PATH = os.path.join(HERMES, "coordinator.db")
KEY_PATH = os.path.join(HERMES, "meta/.evidence_verifier_key")
LEDGER_PATH = os.path.join(HERMES, "meta/evidence/ledger.jsonl")

def get_verifier_key():
    if not os.path.exists(KEY_PATH):
        os.makedirs(os.path.dirname(KEY_PATH), exist_ok=True)
        # Generate 32 bytes hex key
        key = os.urandom(32).hex()
        with open(KEY_PATH, "w", encoding="utf-8") as f:
            f.write(key)
        os.chmod(KEY_PATH, 0o600)
    else:
        with open(KEY_PATH, "r", encoding="utf-8") as f:
            key = f.read().strip()
    return key

def sign_entry(key: str, entry: dict) -> str:
    # Sign over sorted JSON representation of key fields, including the verifier_verdict
    sign_data = {
        "id": entry["id"],
        "ts": entry["ts"],
        "loop": entry["loop"],
        "kind": entry["kind"],
        "claim": entry["claim"],
        "control": entry["control"],
        "before": entry["before"],
        "after": entry["after"],
        "margin": entry["margin"],
        "artifacts": entry["artifacts"],
        "reproduce_cmd": entry["reproduce_cmd"],
        "level": entry["level"],
        "verifier_verdict": entry["verifier_verdict"]
    }
    raw_str = json.dumps(sign_data, sort_keys=True)
    return hmac.new(key.encode("utf-8"), raw_str.encode("utf-8"), hashlib.sha256).hexdigest()

def verify_all():
    key = get_verifier_key()
    
    if not os.path.exists(DB_PATH):
        print("0 verified — no learning proven yet.")
        return 0
        
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # Check if table exists
    cursor = conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='evidence'")
    if cursor.fetchone()[0] == 0:
        print("0 verified — no learning proven yet.")
        conn.close()
        return 0
        
    rows = conn.execute("SELECT * FROM evidence").fetchall()
    if not rows:
        print("0 verified — no learning proven yet.")
        conn.close()
        return 0
        
    verified_count = 0
    for r in rows:
        entry = dict(r)
        entry["artifacts"] = json.loads(entry["artifacts"])
        
        print(f"👁️ Verifying entry {entry['id']} ({entry['loop']}): '{entry['claim']}'...")
        
        # 1. Re-run reproduce_cmd
        cmd = entry["reproduce_cmd"]
        print(f"  Running: {cmd}")
        t0 = time.time()
        # Run process safely
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
        dur = time.time() - t0
        print(f"  Finished in {dur:.2f}s with exit code {res.returncode}")
        
        # Compare actual results to check PASS/FAIL
        # If exit code is 0, we treat it as PASS, otherwise FAIL
        verdict = "PASS" if res.returncode == 0 else "FAIL"
        print(f"  Verdict: {verdict}")
        
        entry["verifier_verdict"] = verdict
        entry["verifier_sig"] = sign_entry(key, entry)
        
        # Update DB
        conn.execute(
            "UPDATE evidence SET verifier_verdict=?, verifier_sig=? WHERE id=?",
            (entry["verifier_verdict"], entry["verifier_sig"], entry["id"])
        )
        conn.commit()
        
        # Append updated entry to ledger.jsonl
        os.makedirs(os.path.dirname(LEDGER_PATH), exist_ok=True)
        with open(LEDGER_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
            
        if verdict == "PASS":
            verified_count += 1
            
    print(f"🎉 Verification complete. {verified_count} verified proofs recorded.")
    conn.close()
    return verified_count

if __name__ == "__main__":
    sys.exit(0 if verify_all() > 0 else 1)
