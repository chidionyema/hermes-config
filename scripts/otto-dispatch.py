#!/usr/bin/env python3
"""otto-dispatch — the OTTO relay step (Ball 17).

Topology this closes:
    cron -> queue -> queue-curate (writes pending-digest.json) -> THIS -> user
Otto is the dispatcher; the user is the consumer of triaged results only. The curator
no longer delivers raw alerts to the user. This script reads the pending digest, applies
Otto-side triage, AUTO-REMEDIATES mechanical issues, and forwards to the user ONLY what
Otto decides is worth their attention. stdout is what the cron (deliver:origin) sends to
the user; we stay SILENT (no stdout) when nothing is user-worthy.

Triage table (extensible):
  - AUTO_REMEDIATE: source has a known fix-probe. Run it; if it now PASSES the issue is
    resolved silently (logged, not shown to the user). If it still FAILS, escalate to the
    user with a note. This is the "a memory-capacity warning must auto-trigger its fix"
    rule (same shape as continuous-audit), generalised.
  - CLAUDE_AUDIT: source needs a Claude audit (correction-audit) -> forward as actionable.
  - default: forward to the user as actionable.

Every decision is recorded to queue/dispatch-log.jsonl; the pending digest is moved aside
to .processed so it is not re-dispatched.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

HERMES = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
QDIR = os.path.join(HERMES, "queue")
DIGEST = os.path.join(QDIR, "pending-digest.json")
DLOG = os.path.join(QDIR, "dispatch-log.jsonl")
SCRIPTS = os.path.join(HERMES, "scripts")

# source -> remediation probe (relative to scripts/). Exit 0 = the issue is now fixed.
AUTO_REMEDIATE = {
    "memory-capacity": "memory-capacity-probe.sh",
    "idle-continuous-learning": "idle-learning-probe.sh",
}
QUEUE_CLI = os.path.join(SCRIPTS, "hermes_queue.py")
# sources that require a Claude audit rather than an automated fix.
CLAUDE_AUDIT = {"correction-audit"}


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log(rec):
    rec["ts"] = _now()
    os.makedirs(QDIR, exist_ok=True)
    with open(DLOG, "a") as f:
        f.write(json.dumps(rec) + "\n")


def _run_probe(name):
    """Run a remediation/verification probe. True=fixed, False=still failing, None=absent."""
    path = os.path.join(SCRIPTS, name)
    if not os.path.exists(path):
        return None
    try:
        r = subprocess.run(["bash", path], capture_output=True, text=True,
                            timeout=120, env={**os.environ, "HERMES_HOME": HERMES})
        return r.returncode == 0
    except Exception:
        return False


def _resolve(fingerprint):
    """Probe-verified resolution: clear the fingerprint from the open queue so it does
    not re-surface every tick. Only called after the source's fix-probe PASSED."""
    if not fingerprint or not os.path.exists(QUEUE_CLI):
        return
    try:
        subprocess.run(["python3", QUEUE_CLI, "resolve", "--fingerprint", fingerprint],
                       capture_output=True, text=True, timeout=30,
                       env={**os.environ, "HERMES_HOME": HERMES})
    except Exception:
        pass


def _clear():
    try:
        os.replace(DIGEST, DIGEST + ".processed")
    except Exception:
        pass


def main():
    if not os.path.exists(DIGEST):
        return 0  # nothing to dispatch
    try:
        d = json.load(open(DIGEST))
    except Exception:
        return 0
    items = d.get("items", [])
    if not items:
        _clear()
        return 0

    user_worthy = []   # forwarded to the user
    auto_handled = []  # remediated silently by Otto

    for it in items:
        src = it.get("source", "")
        if src in AUTO_REMEDIATE:
            ok = _run_probe(AUTO_REMEDIATE[src])
            if ok:
                auto_handled.append(it)
                _resolve(it.get("fingerprint", ""))  # probe-verified clear
                _log({"action": "auto-remediated", "source": src,
                      "fingerprint": it.get("fingerprint")})
                continue
            # remediation failed (or probe absent) -> the user must know
            it = {**it, "_note": "auto-remediation FAILED — needs attention"}
        if src in CLAUDE_AUDIT:
            it = {**it, "_note": "Claude audit required (continuous-audit rule)"}
        user_worthy.append(it)
        _log({"action": "forwarded", "source": src,
              "fingerprint": it.get("fingerprint")})

    _clear()

    if not user_worthy:
        # Everything was auto-handled — Otto absorbed it, the user is not bothered.
        return 0

    lines = ["\U0001f9ed Otto triage — %d issue(s) need you:" % len(user_worthy)]
    for it in user_worthy:
        note = (" — " + it["_note"]) if it.get("_note") else ""
        lines.append("  [%4s] x%-3d %s: %s%s" % (
            it.get("severity", "?"), it.get("count", 1), it.get("source", "?"),
            str(it.get("fingerprint", ""))[:80], note))
    if auto_handled:
        lines.append("(%d issue(s) auto-remediated by Otto, not shown)" % len(auto_handled))
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
