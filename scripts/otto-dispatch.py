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
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from known_classes import classify

# Claude-handback gate: before Otto self-fixes or escalates, defer to a live Claude dispatch on the
# same topic (a `otto-claude-<topic>` tmux session). Best-effort — if the module or tmux is absent,
# degrade to today's behaviour (every issue reads as 'clear'), never break the dispatcher.
try:
    from claude_handback_gate import check_issue, live_claude_sessions
except Exception:  # pragma: no cover - import guard
    def live_claude_sessions(*a, **k):
        return []

    def check_issue(*a, **k):
        return {"verdict": "clear", "session": None, "topic": None, "receipt": None}

HERMES = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
QDIR = os.path.join(HERMES, "queue")
DIGEST = os.path.join(QDIR, "pending-digest.json")
STATE = os.path.join(QDIR, "state.json")
DLOG = os.path.join(QDIR, "dispatch-log.jsonl")
DEDUP_STATE = os.path.join(QDIR, "dispatch-dedup.json")
SCRIPTS = os.path.join(HERMES, "scripts")
QUEUE_CLI = os.path.join(SCRIPTS, "hermes_queue.py")
DEDUP_MIN = int(os.environ.get("HERMES_DISPATCH_DEDUP_MIN", "30"))
# Cron-budget pattern (per cron-budget-subprocess-pattern.md): bound the whole
# dispatcher under the 120s cron cap. If we run out, log it and exit 0 — next
# tick picks up. We never want the dispatcher itself to time out, because that
# is the user-facing pipeline.
DISPATCH_BUDGET_S = int(os.environ.get("HERMES_DISPATCH_BUDGET_S", "100"))
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
    # start_new_session=True + killpg on timeout: a probe handler that spawns its
    # own subprocesses (e.g. pytest) must NOT leak them when we hit the 2s cap.
    # Before this fix, the 2s timeout killed only the handler PID, orphaning its
    # children — the orphaned-pytest meltdown (2026-06-19).
    proc = None
    try:
        proc = subprocess.Popen(runner, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, start_new_session=True,
                                env={**os.environ, "HERMES_HOME": HERMES})
        proc.communicate(timeout=2)
        ok = proc.returncode == 0
        cache.update({"ok": ok, "ts": now, "running": 0})
        return ok
    except subprocess.TimeoutExpired:
        _killpg(proc)
        cache.update({"ok": False, "ts": now, "running": 0})
        return False
    except Exception:
        _killpg(proc)
        cache.update({"ok": False, "ts": now, "running": 0})
        return False


def _killpg(proc):
    if proc is None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        proc.wait(timeout=5)
    except Exception:
        pass


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
    """True if this exact user-worthy set was already delivered within DEDUP_MIN.

    The hash keys on (source, severity, sample) tuples, NOT raw fingerprints —
    fingerprints canonicalize numbers away, so all "TIMEOUT (> 90s)" and
    "TIMEOUT (> 20s)" would hash identically even though they're the same
    condition. The sample is the human-readable value the user saw, so it
    stabilizes the "what was reported" identity across the dedup window.
    """
    key = hashlib.sha1(
        "|".join(sorted(
            "%s/%s/%s" % (it.get("source", "?"), it.get("severity", "?"),
                          (it.get("_sample") or it.get("fingerprint", ""))[:120])
            for it in user_worthy
        )).encode()
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


def _load_samples():
    """Read state.json and return fingerprint -> sample (the human-readable message)."""
    try:
        fps = json.load(open(STATE)).get("fingerprints", {})
    except Exception:
        return {}
    return {fp: v.get("sample", "") for fp, v in fps.items()}


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

    samples = _load_samples()
    first_epochs = _first_epoch_map()
    user_worthy, auto_handled = [], 0  # auto_handled is a COUNTER (was [] — crashed on +=1)
    # Issues a live Claude session already owns — Otto stands down (no self-fix, no escalation).
    claude_owned = []
    claude_sessions = live_claude_sessions()  # one `tmux ls`; [] if no tmux / no claude sessions
    t_start = time.monotonic()
    budget_exceeded = False

    for it in items:
        # Cron-budget check: bail out cleanly if we've eaten most of our window.
        # We log every item we DIDN'T process as "budget_exceeded" so it's
        # visible in the dispatch log; the next tick (5 min later) re-reads the
        # digest and picks up the rest. We never want the dispatcher itself to
        # be the thing that hits the 120s cron cap.
        if time.monotonic() - t_start > DISPATCH_BUDGET_S:
            budget_exceeded = True
            _log({"action": "budget_exceeded", "elapsed_s": int(time.monotonic() - t_start),
                  "items_left": len(items) - len(user_worthy) - auto_handled})
            break
        src, fp = it.get("source", ""), it.get("fingerprint", "")
        sample = samples.get(fp, "")
        # PRE-ACTION GATE: if a live Claude session is dispatched on this topic, Otto must NOT do
        # executor work (self-fix) or raise a competing escalation — it defers and surfaces the
        # handback. This is the structural fix for the 2026-06-20 coordination failure where Otto
        # proposed raising a timeout while `otto-claude-signalengine` had already landed fddef58.
        if claude_sessions:
            g = check_issue(src, sample, fp, sessions=claude_sessions)
            if g["verdict"] != "clear":
                claude_owned.append({**it, "_gate": g, "_sample": sample})
                _log({"action": "deferred_to_claude", "verdict": g["verdict"], "source": src,
                      "fingerprint": fp, "session": g.get("session"),
                      "receipt": g.get("receipt")})
                continue
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
                if os.environ.get("HERMES_PROOF_REPLAY") != "1":
                    try:
                        import coordinator as C
                        conn = C.connect()
                        try:
                            # Check if this fingerprint was previously escalated
                            row = conn.execute(
                                "SELECT id FROM tasks WHERE source=? AND status='escalated' LIMIT 1",
                                (fp,)
                            ).fetchone()
                            if row:
                                task_id = row["id"]
                                # Emit event
                                C.add_event(conn, task_id, "class_auto_learned", json.dumps({"class": cls["name"], "fingerprint": fp}))
                                # Log evidence entry
                                evidence_id = f"proof-known_class-{int(time.time())}"
                                C.log_evidence(
                                    conn=conn,
                                    id=evidence_id,
                                    loop="known_class",
                                    kind="operational_learning",
                                    claim=f"Failure class '{cls['name']}' automatically resolved",
                                    control="escalated",
                                    before="escalated",
                                    after="auto_resolved",
                                    margin=0.0,
                                    artifacts={"fingerprint": fp, "class_name": cls["name"]},
                                    reproduce_cmd=f"python3 {SCRIPTS}/prove_learning.py --replay",
                                    level=2
                                )
                        finally:
                            conn.close()
                    except Exception as db_err:
                        import sys
                        sys.stderr.write(f"⚠️ Failed to log operational learning evidence: {db_err}\n")
        escalate, why = _should_escalate(cls, it, resolved, first_epochs)
        if escalate:
            user_worthy.append({**it, "_note": why,
                                "_class": cls["name"] if cls else "NEW",
                                "_sample": samples.get(fp, "")})
            _log({"action": "escalate", "class": cls["name"] if cls else "NEW",
                  "source": src, "fingerprint": fp, "why": why})
        elif not resolved:
            _log({"action": "absorbed", "class": cls["name"] if cls else "?",
                  "source": src, "fingerprint": fp, "why": why})

    _clear()

    if not user_worthy and not claude_owned:
        return 0
    # Dedup over BOTH the triage set and the claude-owned set, so a state-change is delivered at
    # most once per window (claude_owned items default to 'info' severity for the signature).
    dedup_set = user_worthy + [{**c, "severity": c.get("severity", "info")} for c in claude_owned]
    if _deduped(dedup_set):
        _log({"action": "deduped", "n": len(dedup_set)})
        return 0

    # Group by source for scannability. Each line answers: WHAT, WHERE, COUNT.
    sev_emoji = {"crit": "🔴", "error": "🟠", "warn": "🟡", "info": "🔵"}
    by_source = {}
    for it in user_worthy:
        by_source.setdefault(it.get("source", "?"), []).append(it)

    lines = []
    if user_worthy:
        lines.append("🧭 Otto triage — %d issue(s) across %d source(s):" %
                     (len(user_worthy), len(by_source)))
    for src, group in sorted(by_source.items()):
        sev = max((it.get("severity", "warn") for it in group),
                  key=lambda s: {"crit": 3, "error": 2, "warn": 1, "info": 0}.get(s, 1))
        total_count = sum(it.get("count", 1) for it in group)
        lines.append("")
        lines.append("%s %s — %d fingerprint(s), %d total occurrence(s)" %
                     (sev_emoji.get(sev, "•"), src, len(group), total_count))
        for it in group[:5]:  # cap at 5 per source to keep message bounded
            sample = (it.get("_sample", "") or it.get("fingerprint", "")).strip()
            # Trim very long samples
            if len(sample) > 200:
                sample = sample[:197] + "..."
            lines.append("    %s — %s" % (sev_emoji.get(sev, "•"), sample))
        if len(group) > 5:
            lines.append("    ... and %d more" % (len(group) - 5))
    if auto_handled:
        lines.append("")
        lines.append("✓ %d issue(s) self-healed by Otto, not shown" % auto_handled)
    if claude_owned:
        lines.append("")
        lines.append("🤝 Claude already dispatched — Otto stood down (no self-fix):")
        for c in claude_owned[:5]:
            g = c.get("_gate", {})
            verb = "handed back" if g.get("verdict") == "handback" else "in-flight"
            smp = (c.get("_sample") or c.get("fingerprint", "")).strip()
            if len(smp) > 120:
                smp = smp[:117] + "..."
            lines.append("    • %s  [%s · %s]" % (smp, verb, g.get("session")))
            if g.get("receipt"):
                lines.append("        ↳ %s" % g["receipt"][:160])
        if len(claude_owned) > 5:
            lines.append("    ... and %d more" % (len(claude_owned) - 5))
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
