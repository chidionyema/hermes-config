#!/usr/bin/env python3
"""incident_manager.py — Full incident lifecycle: detect → diagnose → fix → verify → resolve → postmortem."""
import json, os, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
HERMES = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
INCIDENTS_DIR = HERMES / "state" / "incidents"
INCIDENTS_DIR.mkdir(parents=True, exist_ok=True)

def _next_id(): return f"inc-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{len(list(INCIDENTS_DIR.glob('*.json')))+1:03d}"

def create_incident(title, severity="warning", affected=None):
    inc = {"id": _next_id(), "title": title, "status": "detected", "severity": severity,
           "affected_projects": affected or [], "detected_at": datetime.now(timezone.utc).isoformat(),
           "resolved_at": None, "duration_minutes": None, "timeline": [],
           "root_cause": None, "fix_actions": [], "auto_resolved": False, "postmortem": None}
    inc["timeline"].append({"ts": inc["detected_at"], "status": "detected", "detail": title})
    _save(inc); return inc

def update_incident(inc_id, status, detail=""):
    inc = _load(inc_id)
    if not inc: return None
    inc["status"] = status
    inc["timeline"].append({"ts": datetime.now(timezone.utc).isoformat(), "status": status, "detail": detail})
    if status == "resolved":
        inc["resolved_at"] = datetime.now(timezone.utc).isoformat()
        dt = datetime.fromisoformat(inc["resolved_at"].replace("Z","+00:00")) - datetime.fromisoformat(inc["detected_at"].replace("Z","+00:00"))
        inc["duration_minutes"] = int(dt.total_seconds() / 60)
    _save(inc); return inc

def resolve_incident(inc_id, fix_actions=None, root_cause=None):
    inc = _load(inc_id)
    if not inc: return None
    inc["status"] = "resolved"; inc["fix_actions"] = fix_actions or []
    inc["root_cause"] = root_cause; inc["resolved_at"] = datetime.now(timezone.utc).isoformat()
    dt = datetime.fromisoformat(inc["resolved_at"].replace("Z","+00:00")) - datetime.fromisoformat(inc["detected_at"].replace("Z","+00:00"))
    inc["duration_minutes"] = int(dt.total_seconds() / 60)
    inc["timeline"].append({"ts": inc["resolved_at"], "status": "resolved", "detail": f"Fixed: {', '.join(fix_actions or [])}"})
    inc["postmortem"] = _generate_postmortem_text(inc); inc["status"] = "postmortem_done"
    _save(inc); return inc

def active_incidents(): return [json.loads(f.read_text()) for f in sorted(INCIDENTS_DIR.glob("*.json")) if json.loads(f.read_text()).get("status") not in ("resolved","postmortem_done")]

def incident_history(days=7):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = []
    for f in sorted(INCIDENTS_DIR.glob("*.json")):
        try:
            inc = json.loads(f.read_text())
            dt = datetime.fromisoformat(inc.get("detected_at","").replace("Z","+00:00"))
            if dt >= cutoff: result.append(inc)
        except: pass
    return result

def check_escalation():
    """L2: Auto-escalate unresolved incidents."""
    for inc in active_incidents():
        dt = datetime.fromisoformat(inc["detected_at"].replace("Z","+00:00"))
        elapsed = (datetime.now(timezone.utc) - dt).total_seconds() / 60
        new_severity = inc["severity"]
        if elapsed > 120: new_severity = "critical"
        elif elapsed > 60: new_severity = "error"
        elif elapsed > 30: new_severity = "warning"
        if new_severity != inc["severity"]:
            inc["severity"] = new_severity
            inc["timeline"].append({"ts": datetime.now(timezone.utc).isoformat(), "status": "escalated", "detail": f"Escalated to {new_severity} after {int(elapsed)}m"})
            _save(inc)
    return active_incidents()

def _generate_postmortem_text(inc):
    return f"## Postmortem: {inc['title']}\n\n**Detected:** {inc['detected_at']}\n**Resolved:** {inc['resolved_at']}\n**Duration:** {inc.get('duration_minutes','?')}min\n**Root cause:** {inc.get('root_cause','?')}\n**Fix:** {', '.join(inc.get('fix_actions',[]))}\n**Timeline:**\n" + "\n".join(f"- {t['ts'][:19]} {t['status']}: {t['detail'][:80]}" for t in inc.get('timeline',[]))

def stats():
    history = incident_history(30)
    total = len(history); resolved = sum(1 for i in history if i.get("status") in ("resolved","postmortem_done"))
    auto = sum(1 for i in history if i.get("auto_resolved"))
    durations = [i.get("duration_minutes",0) for i in history if i.get("duration_minutes")]
    avg_mttr = sum(durations)/max(len(durations),1)
    return {"total":total,"resolved":resolved,"auto_resolved":auto,"avg_mttr_min":round(avg_mttr,1),"open":total-resolved}

def _load(iid):
    for f in INCIDENTS_DIR.glob("*.json"):
        try:
            d = json.loads(f.read_text())
            if d.get("id") == iid: return d
        except: pass
    return None

def _save(inc):
    (INCIDENTS_DIR / f"{inc['id']}.json").write_text(json.dumps(inc, indent=2))

def main():
    import argparse
    p = argparse.ArgumentParser(description="Incident manager")
    p.add_argument("--create", action="store_true"); p.add_argument("--list", action="store_true")
    p.add_argument("--resolve", action="store_true"); p.add_argument("--escalate", action="store_true")
    p.add_argument("--postmortem", action="store_true"); p.add_argument("--stats", action="store_true")
    p.add_argument("--json", action="store_true"); p.add_argument("--id", help="Incident ID")
    p.add_argument("--title", help="Title for --create")
    args = p.parse_args()
    if args.create and args.title:
        r = create_incident(args.title)
    elif args.list: r = active_incidents()
    elif args.resolve and args.id: r = resolve_incident(args.id, ["manual fix"])
    elif args.escalate: r = check_escalation()
    elif args.postmortem and args.id:
        inc = _load(args.id)
        r = {"postmortem": inc.get("postmortem","") if inc else "not found"}
    elif args.stats: r = stats()
    else: r = {"active": len(active_incidents()), "history_7d": len(incident_history(7)), "stats": stats()}
    if args.json: print(json.dumps(r, indent=2, default=str))
    else: print(json.dumps(r, indent=2, default=str))

if __name__ == "__main__": main()
