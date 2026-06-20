#!/usr/bin/env python3
"""prove_learning.py — falsifiable proof of the operational-learning loop.

The claim under test: a failure class that was UNKNOWN (and therefore escalated
to the human) becomes auto-resolved once the estate *learns* it via
`known_classes.load_proposals()`. That is the operational-learning edge that was
previously dead (proposals written, never read).

This proof is CAUSAL and FALSIFIABLE because it does a controlled A/B against
the *same* synthetic fingerprint and reads otto-dispatch's OWN dispatch-log:

  control   : class absent  -> otto-dispatch logs action='escalate'
  treatment : class present -> otto-dispatch logs action='self-healed'

PASS iff control=escalate AND treatment=self-healed (a real delta). If the
load_proposals wiring (known_classes.py:92) were removed, treatment would also
escalate -> control==treatment -> the proof FAILS. It can go RED. That is the
whole point — a proof that cannot fail proves nothing.

Modes:
  (no arg)    standard/seed: create a previously-escalated task, make the class
              known, run dispatch in NORMAL mode so otto-dispatch writes the
              UNVERIFIED ledger entry that evidence_verify.py later signs.
  --replay    run the control+treatment A/B (drives inputs, appends to the raw
              dispatch-log). This is the reproduce_cmd the verifier re-runs and
              the founder can run by hand. Exits 0 iff the delta holds.
  --negative  same as --replay but keeps the class absent in BOTH phases, so
              there is NO delta. Demonstrates the proof CAN fail (exits 1). Used
              to show falsifiability without touching live wiring.

The verifier (evidence_verify.py) does NOT trust this script's PROOF_RESULT
print — it independently reads the dispatch-log. The print is for humans.
"""
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
DISPATCH_LOG = os.path.join(HERMES, "queue", "dispatch-log.jsonl")
SCRIPTS = os.path.join(HERMES, "scripts")
PROBE_PATH = os.path.join(SCRIPTS, "proof-probe.py")
DISPATCH_PATH = os.path.join(SCRIPTS, "otto-dispatch.py")

FINGERPRINT = "__proof_synthetic_failure__"
PROPOSAL = {
    "name": "proof_synthetic_class",
    "match": FINGERPRINT,
    "action": "probe",
    "handler": "proof-probe.py",
    "fingerprint": FINGERPRINT,
}
# dispatch-log action -> ledger before/after vocabulary
VOCAB = {"escalate": "escalated", "self-healed": "auto_resolved"}


def setup_files():
    """A handler that always succeeds, so a KNOWN class auto-resolves."""
    with open(PROBE_PATH, "w", encoding="utf-8") as f:
        f.write("#!/usr/bin/env python3\nimport sys\nsys.exit(0)\n")
    os.chmod(PROBE_PATH, 0o755)


def set_class_known(known: bool):
    """Add/remove ONLY our synthetic proposal line; preserve every real one."""
    lines = []
    if os.path.exists(PROPOSALS):
        with open(PROPOSALS, "r", encoding="utf-8") as f:
            lines = [l for l in f if l.strip() and FINGERPRINT not in l]
    if known:
        lines.append(json.dumps(PROPOSAL) + "\n")
    os.makedirs(os.path.dirname(PROPOSALS), exist_ok=True)
    with open(PROPOSALS, "w", encoding="utf-8") as f:
        f.writelines(lines)


def write_digest():
    os.makedirs(os.path.dirname(DIGEST), exist_ok=True)
    with open(DIGEST, "w", encoding="utf-8") as f:
        json.dump({"items": [{"source": "proof-source", "fingerprint": FINGERPRINT,
                              "severity": "warn", "count": 1}]}, f)


def dispatch_log_count() -> int:
    if not os.path.exists(DISPATCH_LOG):
        return 0
    with open(DISPATCH_LOG, "r", encoding="utf-8") as f:
        return sum(1 for _ in f)


def dispatch_actions_since(offset: int):
    """Actions otto-dispatch logged for OUR fingerprint after line `offset`."""
    if not os.path.exists(DISPATCH_LOG):
        return []
    with open(DISPATCH_LOG, "r", encoding="utf-8") as f:
        lines = f.readlines()
    out = []
    for ln in lines[offset:]:
        ln = ln.strip()
        if not ln:
            continue
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if d.get("fingerprint") == FINGERPRINT and d.get("action"):
            out.append(d["action"])
    return out


def run_dispatch(replay: bool):
    env = dict(os.environ)
    if replay:
        env["HERMES_PROOF_REPLAY"] = "1"
    else:
        env.pop("HERMES_PROOF_REPLAY", None)
    return subprocess.run([sys.executable, DISPATCH_PATH], capture_output=True,
                          text=True, timeout=60, env=env)


def _phase(known: bool):
    """Run one A/B phase; return the dispatch-log action otto-dispatch emitted."""
    set_class_known(known)
    write_digest()
    n0 = dispatch_log_count()
    res = run_dispatch(replay=True)
    if res.returncode != 0:
        sys.stderr.write("dispatch failed: %s\n" % res.stderr[:300])
        return None
    acts = dispatch_actions_since(n0)
    return acts[-1] if acts else None


def run_ab(negative: bool = False) -> bool:
    """Controlled A/B. negative=True keeps class absent in BOTH phases (no delta)."""
    setup_files()
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("DELETE FROM tasks WHERE source=?", (FINGERPRINT,))
        conn.execute("DELETE FROM events WHERE task_id LIKE 'proof-task-%'")
        conn.commit()
    finally:
        conn.close()
    try:
        control = VOCAB.get(_phase(known=False))
        # treatment: class known (or, in --negative, deliberately still unknown)
        treatment = VOCAB.get(_phase(known=(not negative)))
        delta = bool(control and treatment and control != treatment)
        ok = (control == "escalated" and treatment == "auto_resolved")
        print("PROOF_RESULT " + json.dumps(
            {"control": control, "treatment": treatment, "delta": delta, "pass": ok}))
        if ok:
            print("  PASS — unknown class escalated, learned class auto-resolved (causal delta).")
        else:
            print("  FAIL — control=%r treatment=%r (no escalate->auto_resolve delta)." % (control, treatment))
        return ok
    finally:
        set_class_known(False)        # leave the live registry clean
        if os.path.exists(DIGEST):
            try:
                os.remove(DIGEST)
            except OSError:
                pass


def run_seed() -> bool:
    """Seed the UNVERIFIED ledger entry via otto-dispatch in NORMAL mode."""
    setup_files()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("DELETE FROM tasks WHERE source=?", (FINGERPRINT,))
        conn.execute("DELETE FROM events WHERE task_id LIKE 'proof-task-%'")
        conn.commit()
        task_id = "proof-task-%d" % int(time.time())
        conn.execute(
            "INSERT INTO tasks(id, kind, source, title, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, "failure", FINGERPRINT, "Synthetic Proof Failure", "escalated", time.time()))
        conn.commit()
        print("  seed: previously-escalated task %s created" % task_id)

        set_class_known(True)
        write_digest()
        res = run_dispatch(replay=False)     # NORMAL mode -> writes evidence + event
        if res.returncode != 0:
            print("  seed dispatch failed: %s" % res.stderr[:300])
            return False

        ev = conn.execute(
            "SELECT id FROM evidence WHERE loop='known_class' "
            "AND verifier_verdict='UNVERIFIED' ORDER BY ts DESC LIMIT 1").fetchone()
        if not ev:
            print("  seed FAILED: no UNVERIFIED known_class evidence row written.")
            return False
        print("  seed OK: ledger entry %s written (UNVERIFIED, awaiting evidence_verify.py)" % ev["id"])
        return True
    finally:
        set_class_known(False)
        if os.path.exists(DIGEST):
            try:
                os.remove(DIGEST)
            except OSError:
                pass
        conn.close()


if __name__ == "__main__":
    if "--negative" in sys.argv:
        sys.exit(0 if run_ab(negative=True) else 1)
    if "--replay" in sys.argv:
        sys.exit(0 if run_ab(negative=False) else 1)
    sys.exit(0 if run_seed() else 1)
