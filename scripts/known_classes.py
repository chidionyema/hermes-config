"""known_classes — the proactive dispatcher's decision table.

fingerprint/source -> failure class -> action. This is the substrate that turns Otto
from a relay (cron fails -> user reads digest -> user pastes to Claude) into a self-
healer (cron fails -> registry auto-fixes -> user never sees it). An UNKNOWN class is a
NEW failure -> escalate to the user (the only thing worth their attention).

action:
  auto_fix  run handler; exit 0 => fixed (silent + resolve), else evaluate escalation
  probe     run probe;   exit 0 => healthy (silent + resolve), else evaluate escalation
  escalate  always surface to the user (no known self-heal)

escalate_after_h  page the user if first_seen older than this despite repeated auto-fix
unhealable        if still failing, escalate immediately (don't wait for the 24h window)
"""

REGISTRY = [
    {"name": "signal-engine-daemon", "match": "signal-engine", "action": "auto_fix",
     "handler": "signal-engine-daemon-watchdog.sh", "escalate_after_h": 24, "unhealable": False},
    {"name": "prospector", "match": "prospector", "action": "auto_fix",
     "handler": "prospector-run.sh", "escalate_after_h": 24, "unhealable": False},
    # Probe VERIFIES state (read-only, instant) — it must NOT re-run the pytest
    # suite. Pointing this at repo-health-check.py made every dispatch tick respawn
    # 3 pytest runs under a 2s cap (never resolved, orphaned procs). See
    # repo-health-probe.py.
    {"name": "repo-health", "match": "repo-health", "action": "probe",
     "handler": "repo-health-probe.py", "escalate_after_h": 24, "unhealable": False},
    # WAS handler=proving-ground.py: that script runs npm test / pytest across 5 repos and
    # can't finish in otto-dispatch's 2s cap -> killed every tick, always "failing", spawning
    # a test storm. Now a read-only receipt-reader. proving-ground.py stays the scheduled
    # auditor that WRITES the receipt; the probe only READS it. (war-room 2026-06-20)
    {"name": "proving-ground", "match": "proving-ground", "action": "probe",
     "handler": "proving-ground-probe.py", "escalate_after_h": 24, "unhealable": False},
    # WAS auto_fix -> watchdog.py: a watchdog-heals-watchdog feedback loop (re-running the
    # SENSOR as its own "fix", 2s-capped so it never completes -> "still failing" every tick).
    # Now a read-only PROBE that reads the watchdog's recorded state. A sensor is never healed
    # by re-running it; if the watchdog itself is failing/stale, that escalates to a human.
    {"name": "health-watchdog", "match": "health-watchdog", "action": "probe",
     "handler": "watchdog-state-probe.py", "escalate_after_h": 24, "unhealable": False},
    {"name": "memory-capacity", "match": "memory-capacity", "action": "probe",
     "handler": "memory-capacity-probe.sh", "escalate_after_h": 24, "unhealable": False},
    {"name": "idle-continuous-learning", "match": "idle-continuous-learning", "action": "probe",
     "handler": "idle-learning-probe.sh", "escalate_after_h": 24, "unhealable": False},
    {"name": "skill-hygiene", "match": "skill-hygiene", "action": "probe",
     "handler": "skill-hygiene.py", "escalate_after_h": 168, "unhealable": False},
    {"name": "memory-hygiene", "match": "memory-hygiene", "action": "probe",
     "handler": "memory-hygiene.py", "escalate_after_h": 168, "unhealable": False},
    # telemetry / audit classes: no automatic fix — these always reach the user.
    {"name": "dropped-ball", "match": "dropped-ball", "action": "escalate",
     "handler": None, "escalate_after_h": 0, "unhealable": True},
    {"name": "correction-audit", "match": "correction-audit", "action": "escalate",
     "handler": None, "escalate_after_h": 0, "unhealable": True},
]


def load_proposals():
    """Read queue/known-class-proposals.jsonl and load proposed failure classes."""
    import os
    import json
    hermes_dir = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
    proposals_path = os.path.join(hermes_dir, "queue", "known-class-proposals.jsonl")
    extra_classes = []
    if os.path.exists(proposals_path):
        try:
            with open(proposals_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        proposal = json.loads(line)
                        extra_classes.append({
                            "name": proposal.get("name"),
                            "match": proposal.get("match") or proposal.get("fingerprint"),
                            "action": proposal.get("action", "escalate"),
                            "handler": proposal.get("handler"),
                            "escalate_after_h": proposal.get("escalate_after_h", 24),
                            "unhealable": proposal.get("unhealable", False),
                            "fingerprint": proposal.get("fingerprint")
                        })
                    except Exception:
                        pass
        except OSError:
            pass
    return extra_classes


def classify(source, fingerprint=""):
    """Return the matching class dict, or None if this is a NEW (unknown) failure class."""
    hay = "{} {}".format(source or "", fingerprint or "")
    combined = list(REGISTRY)
    combined.extend(load_proposals())
    for c in combined:
        if c["match"] in hay:
            return c
    return None


# ── ENFORCEMENT: a probe must VERIFY state, never re-run the workload ─────────
# This is the structural guard that makes the war-room fixes permanent. The whole
# disease class — repo-health pytest-storm, watchdog-heals-watchdog, proving-ground
# 5-repo storm — was a `probe`/`auto_fix` handler that re-ran heavy/mutating work under
# otto-dispatch's 2s cap. Convention is not enough; the registry now FAILS LOUD (self-test)
# the moment a probe handler is wired to something that spawns a suite or mutates state.
import os as _os
import re as _re

VALID_ACTIONS = {"auto_fix", "probe", "escalate"}
_SCRIPTS_DIR = _os.path.dirname(_os.path.abspath(__file__))
# Signatures that disqualify a handler from being a read-only PROBE. Escalation via the
# relay queue (hermes_queue submit) is allowed; everything below re-runs work or mutates.
_HEAVY_PROBE = _re.compile(
    r"\b(pytest|npm\s+(test|run\s+build|ci|install)|uv\s+run|cargo\s+(test|build)|"
    r"git\s+(add|commit|rm|push)|os\.system)\b")
_MUTATING_WRITE = _re.compile(r"open\([^)]*['\"][wa]\+?['\"]")  # file writes (a probe reads)


def validate():
    """Return a list of structural violations (empty == clean). Cheap, no handler execution."""
    issues = []
    for c in REGISTRY:
        nm = c.get("name", "?")
        if c.get("action") not in VALID_ACTIONS:
            issues.append(f"{nm}: invalid action {c.get('action')!r}")
        handler = c.get("handler")
        if c.get("action") == "escalate":
            if handler is not None:
                issues.append(f"{nm}: escalate must have handler=None")
            continue
        if not handler:
            issues.append(f"{nm}: action {c['action']} requires a handler")
            continue
        path = _os.path.join(_SCRIPTS_DIR, handler)
        if not _os.path.isfile(path):
            issues.append(f"{nm}: handler {handler} does not exist")
            continue
        if c["action"] == "probe":
            try:
                src = open(path, encoding="utf-8", errors="ignore").read()
            except OSError as e:
                issues.append(f"{nm}: cannot read probe handler {handler}: {e}")
                continue
            # Strip docstrings/string-literals AND #-comments so a probe may freely DESCRIBE
            # the heavy bug it replaces ("this used to run pytest...") without tripping itself.
            no_strings = _re.sub(r'""".*?"""|\'\'\'.*?\'\'\'', "", src, flags=_re.DOTALL)
            code = "\n".join(l for l in no_strings.splitlines()
                             if not l.lstrip().startswith("#"))
            if _HEAVY_PROBE.search(code):
                issues.append(f"{nm}: probe handler {handler} re-runs heavy work "
                              f"(pytest/npm/uv/git) — probes must READ state, not run it")
            if _MUTATING_WRITE.search(code):
                issues.append(f"{nm}: probe handler {handler} opens a file for write — "
                              f"a probe must be read-only")
    return issues


def _self_test():
    issues = validate()
    if issues:
        print("known_classes REGISTRY INVALID:")
        for i in issues:
            print(f"  ✗ {i}")
        return 1
    probes = [c["name"] for c in REGISTRY if c["action"] == "probe"]
    print(f"known_classes self-test: PASS — {len(REGISTRY)} classes, "
          f"{len(probes)} probes all read-only & present, no dangling handlers")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_self_test())
