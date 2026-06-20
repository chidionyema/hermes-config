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
DISPATCH_LOG = os.path.join(HERMES, "queue", "dispatch-log.jsonl")
EVALSET_DIR = os.path.join(HERMES, "meta", "rsi_evalsets")

# dispatch-log action -> ledger before/after vocabulary
VOCAB = {"escalate": "escalated", "self-healed": "auto_resolved"}

# Improvement-gate margin (points on the 0..100 evalset scale). Held here, in the
# verifier, INDEPENDENTLY of rsi-orchestrator.py — the changing agent does not get
# to define the bar it must clear.
RSI_MARGIN = 1.0


def _dispatch_log_count():
    if not os.path.exists(DISPATCH_LOG):
        return 0
    with open(DISPATCH_LOG, "r", encoding="utf-8") as f:
        return sum(1 for _ in f)


def _dispatch_actions_since(offset, fingerprint):
    """Actions OTTO-DISPATCH itself logged for `fingerprint` after line `offset`.

    This is the crux of independence: the verdict is read from the
    system-under-test's own append-only log, NOT from anything the proof script
    prints. The proof script only drives the inputs.
    """
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
        if d.get("fingerprint") == fingerprint and d.get("action"):
            out.append(d["action"])
    return out


def _verdict_known_class(entry, res, n0):
    """Independent, falsifiable verdict for a known_class proof.

    Re-derives control/treatment from otto-dispatch's raw log and requires a real
    causal delta that matches what the entry CLAIMS (before -> after). A no-delta
    replay (e.g. if load_proposals were unwired) yields FAIL -> ledger goes RED.
    Returns (verdict, reason).
    """
    before = (entry.get("before") or "").strip()
    after = (entry.get("after") or "").strip()
    fp = (entry.get("artifacts") or {}).get("fingerprint")

    if res.returncode != 0:
        return "FAIL", "reproduce_cmd exited %s" % res.returncode
    if not fp:
        return "FAIL", "entry has no artifacts.fingerprint to observe"
    if before == after:
        return "FAIL", "recorded before==after (%r) — no causal delta to verify" % before

    acts = [VOCAB.get(a, a) for a in _dispatch_actions_since(n0, fp)]
    if len(acts) < 2:
        return "FAIL", "expected control+treatment actions in dispatch-log, saw %r" % acts
    control, treatment = acts[0], acts[-1]
    if control == treatment:
        return "FAIL", ("no effect: control==treatment==%r (would also fire if the "
                        "learning loop were unwired)" % control)
    if control != before or treatment != after:
        return "FAIL", ("observed %s->%s != claimed %s->%s"
                        % (control, treatment, before, after))
    return "PASS", "observed %s->%s matches claim, causal delta confirmed" % (control, treatment)

def _rsi_score(prompt_var, prompt_text, split):
    """Independent re-implementation of the prompt scorer.

    Deliberately NOT imported from rsi-orchestrator.py: the verifier must compute
    the held-out score from the eval corpus itself, so a changed scorer in the
    orchestrator cannot mint a passing grade. Mirrors the documented rule
    semantics (vars / brevity / clarity|adversarial keyword coverage).
    """
    path = os.path.join(EVALSET_DIR, "%s.jsonl" % prompt_var)
    if not os.path.exists(path):
        return 0.0
    score = 0.0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rule = json.loads(line)
            except ValueError:
                continue
            if split is not None and rule.get("split") not in (split, None):
                continue
            case_id = rule.get("case_id")
            weight = rule.get("weight", 0.0)
            if case_id == "vars_check":
                if all(v in prompt_text for v in rule.get("rules", [])):
                    score += weight
            elif case_id == "brevity_check":
                max_len = rule.get("max_len", 500)
                length = len(prompt_text)
                if length < max_len:
                    score += weight * (1.0 - (length / max_len))
            elif case_id in ("clarity_check", "adversarial_check"):
                kws = rule.get("keywords", [])
                if kws:
                    matches = sum(1 for kw in kws if kw.lower() in prompt_text.lower())
                    score += weight * (matches / len(kws))
    return round(score, 2)


def _evalset_hash(prompt_var):
    path = os.path.join(EVALSET_DIR, "%s.jsonl" % prompt_var)
    if not os.path.exists(path):
        return ""
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _verdict_rsi(entry, res):
    """Independent, falsifiable verdict for an RSI prompt-improvement proof.

    Re-scores the stored baseline & candidate prompts on the HELD-OUT test split
    itself and confirms the candidate beats the baseline by a margin. A no-delta
    or regressed candidate (e.g. prove_rsi.py --negative) yields FAIL -> RED.
    Returns (verdict, reason).
    """
    art = entry.get("artifacts") or {}
    pv = art.get("prompt_variable")
    base = art.get("baseline_prompt")
    cand = art.get("candidate_prompt")
    if not pv or base is None or cand is None:
        return "FAIL", "entry missing prompt_variable/baseline_prompt/candidate_prompt to re-score"

    # The test set must not have been swapped since the proof was recorded.
    recorded_hash = art.get("evalset_hash")
    if recorded_hash and recorded_hash != _evalset_hash(pv):
        return "FAIL", "eval corpus changed since proof was recorded (hash mismatch) — refusing to verify"

    base_test = _rsi_score(pv, base, "test")
    cand_test = _rsi_score(pv, cand, "test")

    # The human-facing reproduce_cmd must agree (defense in depth).
    if res.returncode != 0:
        return "FAIL", "reproduce_cmd (--rescore) exited %s; independent re-score was %s->%s" % (
            res.returncode, base_test, cand_test)

    if not (cand_test > base_test + RSI_MARGIN):
        return "FAIL", ("no held-out improvement: candidate %.2f vs baseline %.2f (need +%.1f) — "
                        "would also fire if the tune overfit the train ruler" % (cand_test, base_test, RSI_MARGIN))

    # Cross-check the orchestrator's claimed numbers against ours; a liar fails.
    try:
        claimed_before = float((entry.get("before") or "").strip())
        claimed_after = float((entry.get("after") or "").strip())
        if abs(claimed_before - base_test) > 0.5 or abs(claimed_after - cand_test) > 0.5:
            return "FAIL", ("claimed %s->%s disagrees with independent re-score %.2f->%.2f"
                            % (entry.get("before"), entry.get("after"), base_test, cand_test))
    except (TypeError, ValueError):
        pass

    return "PASS", "held-out test score rose %.2f->%.2f (margin %.2f), independently re-scored" % (
        base_test, cand_test, cand_test - base_test)


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
        
        # 1. Re-run reproduce_cmd, snapshotting the raw dispatch-log first so we
        #    can read the system-under-test's OWN output (not the proof's print).
        cmd = entry["reproduce_cmd"]
        print(f"  Running: {cmd}")
        n0 = _dispatch_log_count()
        t0 = time.time()
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=180)
        dur = time.time() - t0
        print(f"  Finished in {dur:.2f}s with exit code {res.returncode}")

        # 2. Independent, falsifiable verdict — by loop. The verifier derives the
        #    verdict itself; it never trusts a number the changing agent printed.
        if entry["loop"] == "known_class":
            verdict, reason = _verdict_known_class(entry, res, n0)
        elif entry["loop"] == "rsi":
            verdict, reason = _verdict_rsi(entry, res)
        else:
            # We refuse to mint a PASS for loops we cannot independently check.
            verdict, reason = "UNVERIFIED", "no independent verifier for loop=%r yet" % entry["loop"]
        print(f"  Verdict: {verdict} — {reason}")

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
