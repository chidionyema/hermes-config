#!/usr/bin/env python3
import os
import sys
import json
import time
import sqlite3
import subprocess

HERMES = os.path.expanduser("~/.hermes")
DB_PATH = os.path.join(HERMES, "coordinator.db")
PROPOSALS = os.path.join(HERMES, "queue", "known-class-proposals.jsonl")
DIGEST = os.path.join(HERMES, "queue", "pending-digest.json")
SCRIPTS = os.path.join(HERMES, "scripts")
PROBE_PATH = os.path.join(SCRIPTS, "proof-probe.py")
DISPATCH_PATH = os.path.join(SCRIPTS, "otto-dispatch.py")

FINGERPRINT = "__proof_synthetic_failure__"

def setup_files():
    # 1. Create proof-probe.py that exits 0
    with open(PROBE_PATH, "w", encoding="utf-8") as f:
        f.write("#!/usr/bin/env python3\nimport sys\nsys.exit(0)\n")
    os.chmod(PROBE_PATH, 0o755)

def clean_state(conn):
    # Clean tasks, events, and evidence matching the synthetic fingerprint
    conn.execute("DELETE FROM tasks WHERE source=?", (FINGERPRINT,))
    conn.execute("DELETE FROM events WHERE task_id LIKE 'proof-task-%'")
    conn.execute("DELETE FROM evidence WHERE reproduce_cmd LIKE '%prove_learning.py%'")
    conn.commit()

def run_test(replay_mode=False):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    try:
        if not replay_mode:
            print("🚀 Running prove_learning.py in standard mode...")
            
            setup_files()
            clean_state(conn)
            
            # --- 1. Control Phase: Task was escalated previously ---
            task_id = f"proof-task-{int(time.time())}"
            conn.execute(
                "INSERT INTO tasks(id, kind, source, title, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (task_id, "failure", FINGERPRINT, "Synthetic Proof Failure", "escalated", time.time())
            )
            conn.commit()
            print(f"  Control task created: {task_id} with status 'escalated'")
            
            # --- 2. Learn Phase: Write class proposal ---
            proposal = {
                "name": "proof_synthetic_class",
                "match": FINGERPRINT,
                "action": "probe",
                "handler": "proof-probe.py",
                "fingerprint": FINGERPRINT,
                "proposed_at": time.time()
            }
            # Append proposal
            os.makedirs(os.path.dirname(PROPOSALS), exist_ok=True)
            with open(PROPOSALS, "a", encoding="utf-8") as f:
                f.write(json.dumps(proposal) + "\n")
            print("  Proposal appended to known-class-proposals.jsonl")
            
            # --- 3. Treatment Phase: Run dispatch on recurrence ---
            os.makedirs(os.path.dirname(DIGEST), exist_ok=True)
            digest_content = {
                "items": [
                    {
                        "source": "proof-source",
                        "fingerprint": FINGERPRINT,
                        "severity": "warn",
                        "count": 1
                    }
                ]
            }
            with open(DIGEST, "w", encoding="utf-8") as f:
                json.dump(digest_content, f)
            print("  Digest written with synthetic failure fingerprint")
            
            # Run otto-dispatch.py
            print("  Running otto-dispatch.py...")
            res = subprocess.run([sys.executable, DISPATCH_PATH], capture_output=True, text=True, timeout=60)
            print(f"  Dispatch exited with code {res.returncode}")
            if res.returncode != 0:
                print(f"  Stderr: {res.stderr}")
                return False
                
            # --- 4. Assertions ---
            # Check event class_auto_learned logged in DB
            row_event = conn.execute(
                "SELECT count(*) c FROM events WHERE task_id=? AND kind='class_auto_learned'",
                (task_id,)
            ).fetchone()
            if row_event["c"] == 0:
                print("  ❌ Assertion failed: No class_auto_learned event logged for control task.")
                return False
                
            # Check evidence entry logged in DB
            row_ev = conn.execute(
                "SELECT * FROM evidence WHERE loop='known_class' AND verifier_verdict='UNVERIFIED' LIMIT 1"
            ).fetchone()
            if not row_ev:
                print("  ❌ Assertion failed: No evidence ledger entry found matching operational learning.")
                return False
                
            print("  ✅ Operational learning closed loop verified successfully!")
            return True
            
        else:
            print("🚀 Running prove_learning.py in REPLAY mode...")
            
            # Clean up pending-digest and force resolution check
            setup_files()
            
            # Write digest
            os.makedirs(os.path.dirname(DIGEST), exist_ok=True)
            digest_content = {
                "items": [
                    {
                        "source": "proof-source",
                        "fingerprint": FINGERPRINT,
                        "severity": "warn",
                        "count": 1
                    }
                ]
            }
            with open(DIGEST, "w", encoding="utf-8") as f:
                json.dump(digest_content, f)
                
            # Make sure there is a control task marked escalated so it logs again
            # Delete old evidence/events from previous replay
            conn.execute("DELETE FROM events WHERE task_id LIKE 'proof-task-%'")
            conn.execute("DELETE FROM evidence WHERE reproduce_cmd LIKE '%prove_learning.py%'")
            conn.execute("DELETE FROM tasks WHERE source=?", (FINGERPRINT,))
            conn.commit()
            
            task_id = f"proof-task-{int(time.time())}"
            conn.execute(
                "INSERT INTO tasks(id, kind, source, title, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (task_id, "failure", FINGERPRINT, "Synthetic Proof Failure", "escalated", time.time())
            )
            conn.commit()
            
            # Run dispatcher
            res = subprocess.run([sys.executable, DISPATCH_PATH], capture_output=True, text=True, timeout=60)
            if res.returncode != 0:
                print(f"  ❌ Replay dispatcher run failed: {res.stderr}")
                return False
                
            # Verify evidence got generated
            row_ev = conn.execute(
                "SELECT * FROM evidence WHERE loop='known_class' LIMIT 1"
            ).fetchone()
            if not row_ev:
                print("  ❌ Replay verification failed: No evidence recorded.")
                return False
                
            print("  ✅ Replay proof succeeded!")
            return True
            
    finally:
        conn.close()
        # Clean up digest file
        if os.path.exists(DIGEST):
            try:
                os.remove(DIGEST)
            except OSError:
                pass

if __name__ == "__main__":
    replay = "--replay" in sys.argv
    success = run_test(replay)
    sys.exit(0 if success else 1)
