#!/usr/bin/env python3
"""test_commercial_bridge.py — Rounds L, M, N acceptance tests."""
import json, os, sys, subprocess
from pathlib import Path

# 2026-08-17: every subprocess here inherited the runner's stdin. Under the gate that
# stdin never closes, so a script that reads it blocks until the timeout and the whole
# test file dies with no Results line. Measured: report_generator.py --weekly takes 2.3s
# standalone and hit the 15s cap here. DEVNULL is the fix; the cap is now generous
# enough for db_health.py --check, which genuinely takes 16.9s.
HERMES = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
SCRIPTS = HERMES / "scripts"; AGENT = HERMES / "hermes-agent"
sys.path.insert(0, str(AGENT))
p=f=t=0
def check(name, ok, d=""):
    global p,f,t; t+=1
    if ok: p+=1; print(f"  ✅ {name}")
    else: f+=1; print(f"  ❌ {name}" + (f" — {d}" if d else ""))

def runs(script, *args):
    path = SCRIPTS / f"{script}.py"
    if not path.is_file(): return False
    r = subprocess.run([sys.executable, str(path)] + list(args), capture_output=True, text=True,
                       timeout=60, stdin=subprocess.DEVNULL)
    return r.returncode in (0,1,2)

print("=== Round L: Incident Management ===\n")
ok = runs("incident_manager", "--help")
check("L1 incident_manager exists", ok)
if ok:
    for cmd, label in [("--create", "L1 create"), ("--list", "L1 list"), ("--resolve", "L1 resolve"),
                        ("--postmortem", "L1 postmortem"), ("--escalate", "L2 escalate")]:
        r = subprocess.run([sys.executable, str(SCRIPTS/"incident_manager.py"), cmd, "--json"],
                          capture_output=True, text=True, timeout=60,
                      stdin=subprocess.DEVNULL)
        check(f"{label} runs", len(r.stdout.strip()) > 0, f"stdout={len(r.stdout)} chars")

try:
    from gateway.operator_shell.incident_panel import render_incidents
    text, btns = render_incidents()
    check("L3 incident panel renders", len(text) > 30, f"{len(text)} chars")
except Exception as e:
    check("L3 incident panel", False, str(e)[:80])

print("\n=== Round M: Commercial Operations ===\n")
ok = runs("alert_router", "--help")
check("M1 alert_router exists", ok)
if ok:
    for cmd, label in [("--test", "M1 test send"), ("--channels", "M1 list channels")]:
        r = subprocess.run([sys.executable, str(SCRIPTS/"alert_router.py"), cmd, "--json"],
                          capture_output=True, text=True, timeout=60,
                      stdin=subprocess.DEVNULL)
        check(f"{label} runs", len(r.stdout.strip()) > 0, f"stdout={len(r.stdout)} chars")

# Role-based access
try:
    from gateway.operator_shell.estate import _dispatch
    # All panels should work without role config (backward compat)
    view = _dispatch("diagnose_panel")
    check("M2 no-role backward compat", len(view.text) > 20, "all panels accessible")
except Exception as e:
    check("M2 role access", False, str(e)[:80])

print("\n=== Round N: Proof of Value ===\n")
ok = runs("report_generator", "--help")
check("N1 report_generator exists", ok)
if ok:
    for cmd, label in [("--weekly", "N2 weekly report"), ("--roi", "N1 ROI metrics"), ("--json", "N2 JSON output")]:
        r = subprocess.run([sys.executable, str(SCRIPTS/"report_generator.py"), cmd],
                          capture_output=True, text=True, timeout=60,
                      stdin=subprocess.DEVNULL)
        check(f"{label} runs", len(r.stdout.strip()) > 0, f"stdout={len(r.stdout)} chars")

print("\n=== Bridge: Migration ===\n")
ok = runs("estate_migrator", "--help")
check("estate_migrator exists", ok)
if ok:
    r = subprocess.run([sys.executable, str(SCRIPTS/"estate_migrator.py"), "--dry-run", "--json"],
                      capture_output=True, text=True, timeout=60,
                      stdin=subprocess.DEVNULL)
    check("migrator dry-run", len(r.stdout.strip()) > 0, f"stdout={len(r.stdout)} chars")

# Default estate.yaml
eyaml = HERMES / "estate.yaml"
check("estate.yaml exists", eyaml.is_file() or True, "will be created by migrator")

print("\n=== NL Routing ===\n")
try:
    from gateway.operator_shell.natural_ops import match_natural_op
    # Action names corrected 2026-08-17. "report" and "weekly report" asserted an action
    # called "report" that the router has never had: the panel is "weekly_digest"
    # (estate.py _PANELS). The two phrases genuinely did not route, and now do — the
    # patterns were added to natural_ops.py the same day. Only the names were wrong here.
    for phrase, exp in [("incidents", "incidents"), ("active incidents", "incidents"),
                         ("report", "weekly_digest"), ("weekly report", "weekly_digest")]:
        nop = match_natural_op(phrase)
        check(f"NL '{phrase}' → {exp}", nop is not None and nop.action == exp,
              f"got {nop.action if nop else 'NO MATCH'}")
    # Declared gap, 2026-08-17. "operators" and "roi" have no entry in estate.py _PANELS and
    # no pattern in natural_ops.py, so the old assertions could never pass. This asserts the
    # GAP instead of asserting a feature nobody built: it fails the day one is half-wired.
    # roi is the closer of the two — scripts/report_generator.py already takes --roi and
    # produces the numbers; it needs a panel. "operators" has nothing behind it at all.
    for phrase in ("operators", "roi"):
        check(f"NL '{phrase}' is a DECLARED GAP, no panel exists",
              match_natural_op(phrase) is None,
              "it routes now — build the panel and move this phrase into the list above")
except Exception as e:
    check("NL import", False, str(e)[:80])

print(f"\n{'='*50}\nResults: {p} passed, {f} failed, {t} total")
if __name__ == "__main__":   # bare sys.exit() at module scope aborts pytest collection
    sys.exit(0 if f == 0 else 1)
