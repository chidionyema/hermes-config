#!/usr/bin/env python3
"""otto-dispatch — the proactive relay step (Ball 17 + proactive-substrate).

Topology:
    cron -> queue -> queue-curate (pending-digest.json) -> THIS -> user

Otto is the coordinator, not a relay. For every pending fingerprint this script asks the
known-class registry (known_classes.py) what to do:

  auto_fix / probe  -> run the handler. If it resolves the issue, the fingerprint is
                       cleared and the user is NEVER told (silent self-heal).
  still failing      -> the user-facing gate decides: surface ONLY if the class is NEW,
                       has been failing > escalate_after_h, or is an unhealable crit.
  escalate           -> surface (telemetry / audit classes).

Two further guarantees the user demanded:
  * DEDUP: the exact same user-worthy set is delivered AT MOST once per
    HERMES_DISPATCH_DEDUP_MIN (default 30) minutes. One delivery per state-change,
    not one per 5-minute tick.
  * SILENCE: stdout is emitted ONLY when there is something genuinely new for the user.
    Everything self-healed or deduped produces no stdout (the cron is deliver:origin,
    so no stdout == no Telegram message).

Every decision is logged to queue/dispatch-log.jsonl.
"""
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from known_classes import classify

HERMES = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
QDIR = os.path.join(HERMES, "queue")
DIGEST = os.path.join(QDIR, "pending-digest.json")
STATE = os.path.join(QDIR, "state.json")
DLOG = os.path.join(QDIR, "dispatch-log.jsonl")
DEDUP_STATE = os.path.join(QDIR, "dispatch-dedup.json")
SCRIPTS = os.path.join(HERMES, "scripts")
QUEUE_CLI = os.path.join(SCRIPTS, "hermes_queue.py")
DEDUP_MIN = int(os.environ.get("HERMES_DISPATCH_DEDUP_MIN", "30"))
_HANDLER_CACHE = {}


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log(rec):
    rec["ts"] = _now()
    os.makedirs(QDIR, exist_ok=True)
    with open(DLOG, "a") as f:
        f.write(json.dumps(rec) + "\n")


def _run_handler(name):
    """Run a fix/probe handler. True=resolved(exit 0), False=still failing, None=absent.
    Bounded at 2s; handlers are quick probes/fixes, slow = broken.
    Caches per-handler success for 5 min so repeated fingerprints don't re-run."""
    path = os.path.join(SCRIPTS, name)
    if not os.path.exists(path):
        return None
    now = time.time()
    cache = _HANDLER_CACHE.setdefault(name, {})
    if cache.get("ok") and (now - cache.get("ts", 0)) < 300:
        return True
    if cache.get("running") and (now - cache.get("running", 0)) < 10:
        return False
    cache["running"] = now
    runner = ["python3", path] if name.endswith(".py") else ["bash", path]
    try:
        r = subprocess.run(runner, capture_output=True, text=True, timeout=2,
                           env={**os.environ, "HERMES_HOME": HERMES})
        ok = r.returncode == 0
        cache.update({"ok": ok, "ts": now, "running": 0})
        return ok
    except subprocess.TimeoutExpired:
        cache.update({"ok": False, "ts": now, "running": 0})
        return False
    except Exception:
        cache.update({"ok": False, "ts": now, "running": 0})
        return False


def _resolve(fingerprint):
    if not fingerprint or not os.path.exists(QUEUE_CLI):
        return
    try:
        subprocess.run(["python3", QUEUE_CLI, "resolve", "--fingerprint", fingerprint],
                       capture_output=True, text=True, timeout=30,
                       env={**os.environ, "HERMES_HOME": HERMES})
    except Exception:
        pass


def _first_epoch_map():
    """fingerprint -> first_seen epoch, read from the queue state."""
    out = {}
    try:
        fps = json.load(open(STATE)).get("fingerprints", {})
        for fp, v in fps.items():
            fs = v.get("first_seen", "")
            try:
                out[fp] = datetime.strptime(fs, "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=timezone.utc).timestamp()
            except Exception:
                out[fp] = v.get("last_epoch", time.time())
    except Exception:
        pass
    return out


def _age_hours(fp, first_epochs):
    fe = first_epochs.get(fp)
    return (time.time() - fe) / 3600 if fe else 0.0


def _clear():
    try:
        os.replace(DIGEST, DIGEST + ".processed")
    except Exception:
        pass


def _deduped(user_worthy):
    """True if this exact user-worthy set was already delivered within DEDUP_MIN."""
    key = hashlib.sha1(
        "|".join(sorted(it.get("fingerprint", "") for it in user_worthy)).encode()
    ).hexdigest()
    now = time.time()
    try:
        prev = json.load(open(DEDUP_STATE))
        if prev.get("hash") == key and (now - prev.get("ts", 0)) < DEDUP_MIN * 60:
            return True
    except Exception:
        pass
    try:
        json.dump({"hash": key, "ts": now}, open(DEDUP_STATE, "w"))
    except Exception:
        pass
    return False


def _should_escalate(cls, item, resolved, first_epochs):
    """The user-facing gate. Surface to the user ONLY when it is genuinely warranted."""
    if cls is None:
        return True, "new failure class"
    if cls["action"] == "escalate":
        return True, "no self-heal (telemetry/audit class)"
    if resolved:
        return False, "self-healed"
    # handler ran and the issue is still failing -> graduated escalation rules
    fp = item.get("fingerprint", "")
    if cls.get("unhealable"):
        return True, "unhealable + still failing"
    if item.get("severity") == "crit":
        return True, "crit could not self-heal"
    if _age_hours(fp, first_epochs) > cls.get("escalate_after_h", 24):
        return True, "failing > %dh despite auto-fix" % cls.get("escalate_after_h", 24)
    return False, "absorbed (will retry next tick)"


def main():
    if not os.path.exists(DIGEST):
        return 0
    try:
        items = json.load(open(DIGEST)).get("items", [])
    except Exception:
        return 0
    if not items:
        _clear()
        return 0

    first_epochs = _first_epoch_map()
    user_worthy, auto_handled = [], 0

    for it in items:
        src, fp = it.get("source", ""), it.get("fingerprint", "")
        cls = classify(src, fp)
        resolved = False
        if cls and cls["action"] in ("auto_fix", "probe") and cls.get("handler"):
            ok = _run_handler(cls["handler"])
            resolved = ok is True
            if resolved:
                _resolve(fp)
                auto_handled += 1
                _log({"action": "self-healed", "class": cls["name"], "source": src,
                      "fingerprint": fp, "handler": cls["handler"]})
        escalate, why = _should_escalate(cls, it, resolved, first_epochs)
        if escalate:
            user_worthy.append({**it, "_note": why,
                                "_class": cls["name"] if cls else "NEW"})
            _log({"action": "escalate", "class": cls["name"] if cls else "NEW",
                  "source": src, "fingerprint": fp, "why": why})
        elif not resolved:
            _log({"action": "absorbed", "class": cls["name"] if cls else "?",
                  "source": src, "fingerprint": fp, "why": why})

    _clear()

    if not user_worthy:
        return 0
    if _deduped(user_worthy):
        _log({"action": "deduped", "n": len(user_worthy)})
        return 0

    lines = ["\U0001f9ed Otto triage — %d issue(s) need you:" % len(user_worthy)]
    for it in user_worthy:
        lines.append("  [%4s] x%-3d %s [%s] — %s" % (
            it.get("severity", "?"), it.get("count", 1), it.get("source", "?"),
            it.get("_class", "?"), it.get("_note", "")))
    if auto_handled:
        lines.append("(%d issue(s) self-healed by Otto, not shown)" % auto_handled)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
