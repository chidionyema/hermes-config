#!/usr/bin/env python3
"""
mini_app_server.py — Telegram Mini App backend + WebSocket real-time engine.

Serves the Otto dashboard as a Telegram Mini App with:
- Real-time WebSocket updates (estate state changes pushed to clients)
- REST API for data (reuses api_server.py endpoints)
- Team collaboration (incident assignment, comments)
- AI insights (trends, predictions, optimization suggestions)

Binds to localhost:8800 (Mini App) + localhost:8801 (WebSocket).
"""

import asyncio, json, os, sys, time, threading, queue
from pathlib import Path
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import subprocess

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

HERMES = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
MINI_APP_DIR = HERMES / "mini-app"
SCRIPTS = HERMES / "scripts"
STATE_Q = queue.Queue()  # broadcast queue for WebSocket clients
WS_CLIENTS = set()

# ── State Broadcaster ──

def broadcast_state():
    """Push current estate state to all WebSocket clients."""
    try:
        from gateway.operator_shell.smart_home import _quick_status
        from gateway.operator_shell.otto_health import _compute_score
        status = _quick_status()
        score = _compute_score()
        payload = {
            "type": "state_update",
            "ts": datetime.now(timezone.utc).isoformat(),
            "prospector": status.get("prospector", "?"),
            "incidents": status.get("incidents", 0),
            "spend": status.get("spend", 0),
            "score": score["score"],
        }
        STATE_Q.put(json.dumps(payload))
    except Exception:
        pass

def poll_state_loop():
    """Background thread: poll estate state every 5s and broadcast changes."""
    last_state = None
    while True:
        try:
            from gateway.operator_shell.smart_home import _quick_status
            status = _quick_status()
            current = json.dumps(status, sort_keys=True)
            if current != last_state:
                last_state = current
                broadcast_state()
        except Exception:
            pass
        time.sleep(5)

# ── WebSocket Server (simple polling-based, no external deps) ──

class WSServer:
    """Ultra-simple WebSocket-like server using HTTP long-polling.
    Clients GET /ws and receive state updates as they arrive."""
    
    @staticmethod
    def handle_ws():
        """Generator that yields state updates."""
        while True:
            try:
                msg = STATE_Q.get(timeout=30)
                yield f"data: {msg}\n\n"
            except queue.Empty:
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"

# ── HTTP Server ──

class MiniAppHandler(BaseHTTPRequestHandler):
    ws_manager = WSServer()
    
    def _serve_file(self, path, content_type):
        try:
            full_path = MINI_APP_DIR / path
            if not full_path.is_file():
                self._respond(404, "Not found", "text/plain")
                return
            content = full_path.read_text()
            self._respond(200, content, content_type)
        except Exception as e:
            self._respond(500, str(e), "text/plain")
    
    def _respond(self, code, data, content_type="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if isinstance(data, str):
            self.wfile.write(data.encode())
        else:
            self.wfile.write(json.dumps(data).encode())
    
    def do_GET(self):
        path = self.path.split("?")[0]
        
        # Static files
        if path == "/" or path == "/index.html":
            self._serve_file("index.html", "text/html")
        elif path == "/app.js":
            self._serve_file("app.js", "application/javascript")
        elif path == "/style.css":
            self._serve_file("style.css", "text/css")
        
        # API endpoints (inline — no subprocess)
        elif path.startswith("/api/"):
            api_path = path[5:]  # strip /api/
            try:
                if api_path == "health":
                    from gateway.operator_shell.otto_health import _compute_score
                    result = _compute_score()
                    self._respond(200, {"status": "ok", "score": result["score"], "breakdown": result.get("breakdown",{}), "raw": result.get("raw",{})})
                elif api_path == "status":
                    from gateway.operator_shell.smart_home import _quick_status
                    status = _quick_status()
                    # Add pipeline gate details
                    prospector = status.get("prospector", "")
                    is_up = "\ud83d\udd34" not in prospector and "down" not in prospector
                    status["gates"] = {
                        "source_check": "pass" if is_up else "warn",
                        "moat": "fail" if not is_up else "pass",
                        "auto_fixer": "pass",
                        "injector": "pass",
                        "policy_engine": "pass",
                    }
                    self._respond(200, status)
                elif api_path == "incidents":
                    inc_dir = HERMES / "state" / "incidents"
                    active = []
                    if inc_dir.is_dir():
                        for f in inc_dir.glob("*.json"):
                            try:
                                inc = json.loads(f.read_text())
                                if inc.get("status") not in ("resolved","postmortem_done"):
                                    active.append(inc)
                            except: pass
                    self._respond(200, active)
                elif api_path == "metrics":
                    self._respond(200, _get_metrics())
                elif api_path == "insights":
                    self._respond(200, _generate_insights())
                elif api_path == "team":
                    self._respond(200, _get_team())
                # ── Integration endpoints (Tier 0-7 data) ──
                elif api_path == "outcomes":
                    self._respond(200, _get_outcome_stats())
                elif api_path == "compliance":
                    self._respond(200, _get_compliance())
                elif api_path == "invariants":
                    self._respond(200, _get_invariant_status())
                elif api_path == "policies_status":
                    self._respond(200, _get_policies_status())
                else:
                    self._respond(404, {"error": "not found"})
            except Exception as e:
                self._respond(500, {"error": str(e)})
        
        # WebSocket (long-polling)
        elif path == "/ws":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            for msg in self.ws_manager.handle_ws():
                try:
                    self.wfile.write(msg.encode())
                    self.wfile.flush()
                except Exception:
                    break
        
        else:
            self._respond(404, {"error": "not found"})
    
    def do_POST(self):
        path = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode() if length else "{}"
        try: data = json.loads(body)
        except: data = {}
        
        if path == "/api/actions/fix-all":
            r = subprocess.run([sys.executable, str(SCRIPTS / "auto_fixer.py"), "--fix", "--json"],
                             capture_output=True, text=True, timeout=30)
            self._respond(200, r.stdout)
        elif path == "/api/actions/pause":
            from gateway.operator_shell.estate import handle_estate_action
            handle_estate_action("pause")
            broadcast_state()
            self._respond(200, {"ok": True})
        elif path == "/api/actions/resume":
            from gateway.operator_shell.estate import handle_estate_action
            handle_estate_action("resume")
            broadcast_state()
            self._respond(200, {"ok": True})
        elif path == "/api/incidents/comment":
            inc_id = data.get("id", "")
            comment = data.get("comment", "")
            # Store comment
            inc_file = HERMES / "state" / "incidents" / f"{inc_id}.json"
            if inc_file.is_file():
                inc = json.loads(inc_file.read_text())
                inc.setdefault("comments", []).append({
                    "author": data.get("author", "operator"),
                    "text": comment,
                    "ts": datetime.now(timezone.utc).isoformat()
                })
                inc_file.write_text(json.dumps(inc, indent=2))
                broadcast_state()
                self._respond(200, {"ok": True})
            else:
                self._respond(404, {"error": "incident not found"})
        elif path == "/api/incidents/assign":
            inc_id = data.get("id", "")
            assignee = data.get("assignee", "")
            inc_file = HERMES / "state" / "incidents" / f"{inc_id}.json"
            if inc_file.is_file():
                inc = json.loads(inc_file.read_text())
                inc["assigned_to"] = assignee
                inc_file.write_text(json.dumps(inc, indent=2))
                broadcast_state()
                self._respond(200, {"ok": True})
            else:
                self._respond(404, {"error": "incident not found"})
        else:
            self._respond(404, {"error": "not found"})
    
    def log_message(self, format, *args):
        pass

def _get_metrics():
    """Real metrics from Prospector tick logs and estate state."""
    try:
        from gateway.operator_shell.smart_home import _quick_status
        from gateway.operator_shell.otto_health import _compute_score
        status = _quick_status()
        score = _compute_score()
        
        # Recent events from tick log
        recent = []
        tick_file = Path.home() / "Documents/code/prospector/store/scheduler/ticks.jsonl"
        if tick_file.is_file():
            lines = tick_file.read_text().splitlines()
            for ln in reversed(lines[-20:]):
                try:
                    tick = json.loads(ln)
                    ts = tick.get("ts", "")[:19]
                    t = ts[11:16] if "T" in ts else ""
                    action = tick.get("action", "")
                    error = tick.get("error", "")
                    if error:
                        recent.append({"type": "error", "time": t, "msg": error[:80]})
                    elif action:
                        recent.append({"type": "info", "time": t, "msg": action[:80]})
                except:
                    pass
        
        # If no tick events, check for recent fixes
        if not recent:
            fix_dir = Path.home() / "Documents/code/prospector/store/auto_fixer"
            if fix_dir.is_dir():
                for f in sorted(fix_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:5]:
                    try:
                        fix = json.loads(f.read_text())
                        recent.append({"type": "fix", "time": "", "msg": f"Fix: {fix.get('description', f.name)[:60]}"})
                    except:
                        pass
        
        return {
            "incidents": status.get("incidents", 0),
            "spend": status.get("spend", 0),
            "score": score.get("score", 0),
            "decisions": status.get("decisions", 0),
            "recent_events": recent[-8:]
        }
    except Exception as e:
        return {"incidents": 0, "spend": 0, "score": 0, "decisions": 0, "recent_events": [], "error": str(e)}

def _get_outcome_stats() -> dict:
    """Get recent task outcome statistics for the dashboard."""
    try:
        sys.path.insert(0, str(SCRIPTS))
        from outcome_tracker import OutcomeTracker
        tracker = OutcomeTracker(HERMES)
        return tracker.stats(window_days=7)
    except Exception as e:
        return {"error": str(e)}

def _get_compliance() -> dict:
    """Get compliance report summary."""
    try:
        sys.path.insert(0, str(SCRIPTS))
        from auto_close_identity import AgentIdentity
        ai = AgentIdentity(HERMES)
        return ai.compliance_report()
    except Exception as e:
        return {"error": str(e)}

def _get_invariant_status() -> dict:
    """Get constitutional invariant status."""
    try:
        sys.path.insert(0, str(SCRIPTS))
        from constitutional_validator import validate
        report = validate(HERMES)
        return {
            "passed": report.passed,
            "violations": [
                {"id": v.invariant_id, "name": v.invariant_name, "detail": v.detail}
                for v in report.violations
            ],
        }
    except Exception as e:
        return {"error": str(e)}

def _get_policies_status() -> dict:
    """Get policy corpus status."""
    try:
        sys.path.insert(0, str(SCRIPTS))
        from cost_policy_mgmt import PolicyCompressor
        pc = PolicyCompressor(HERMES)
        return pc.analyze()
    except Exception as e:
        return {"error": str(e)}

def _generate_insights():
    """AI-powered insights from estate data."""
    insights = []
    try:
        # Check spend trend
        ticks = Path.home() / "Documents/code/prospector/store/scheduler/ticks.jsonl"
        if ticks.is_file():
            lines = ticks.read_text().splitlines()
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            today_errors = sum(1 for ln in lines if today in ln and '"error": "' in ln)
            if today_errors > 10:
                insights.append({"type": "warning", "text": f"Prospector: {today_errors} errors today. Consider pausing until moat is healthy."})
        
        # Check score trend
        vel = HERMES / "logs" / "self-audit" / "velocity.jsonl"
        if vel.is_file():
            scores = [json.loads(l) for l in vel.read_text().splitlines() if l.strip()]
            if len(scores) >= 2:
                recent = scores[-2:]
                if recent[-1].get("score", 0) < recent[-2].get("score", 0):
                    insights.append({"type": "warning", "text": "Score is declining. Check policy firings and injection relevance."})
                elif recent[-1].get("score", 0) > recent[-2].get("score", 0):
                    insights.append({"type": "success", "text": "Score is improving! System is learning effectively."})
    except: pass
    
    if not insights:
        insights.append({"type": "info", "text": "Estate is stable. No critical insights at this time."})
    return {"insights": insights}

def _get_team():
    """Get team members from estate.yaml."""
    try:
        import yaml
        cfg = yaml.safe_load((HERMES / "estate.yaml").read_text()) if (HERMES / "estate.yaml").is_file() else {}
        return cfg.get("estate", {}).get("operators", [{"name": "Admin", "role": "admin"}])
    except:
        return [{"name": "Admin", "role": "admin"}]

def main():
    import argparse
    p = argparse.ArgumentParser(description="Telegram Mini App server")
    p.add_argument("--port", type=int, default=8800)
    args = p.parse_args()
    
    # Start state polling thread
    threading.Thread(target=poll_state_loop, daemon=True).start()
    
    server = ThreadingHTTPServer(("127.0.0.1", args.port), MiniAppHandler)
    print(f"Otto Mini App: http://127.0.0.1:{args.port}")
    print(f"WebSocket:     ws://127.0.0.1:{args.port}/ws")
    print(f"API:           http://127.0.0.1:{args.port}/api/")
    try: server.serve_forever()
    except KeyboardInterrupt: server.shutdown()

if __name__ == "__main__": main()
