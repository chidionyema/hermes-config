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
    {"name": "proving-ground", "match": "proving-ground", "action": "probe",
     "handler": "proving-ground.py", "escalate_after_h": 24, "unhealable": False},
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


def classify(source, fingerprint=""):
    """Return the matching class dict, or None if this is a NEW (unknown) failure class."""
    hay = "{} {}".format(source or "", fingerprint or "")
    for c in REGISTRY:
        if c["match"] in hay:
            return c
    return None
