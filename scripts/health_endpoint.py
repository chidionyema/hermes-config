#!/usr/bin/env python3
"""
health_endpoint.py — Lightweight HTTP health check for uptime monitoring.

Binds to localhost:8699 by default. Responds to GET /health with JSON
estate status. Compatible with UptimeRobot, Pingdom, Healthchecks.io.

Usage: python3 health_endpoint.py [--port 8699]
"""
import json, os, sys, subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime, timezone

HERMES = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))

def get_estate_status():
    """Quick health check — returns in <500ms."""
    status = {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat(), "checks": {}}
    
    # Check gateway process
    try:
        r = subprocess.run(["pgrep", "-f", "gateway run"], capture_output=True, timeout=3)
        status["checks"]["gateway"] = "running" if r.returncode == 0 else "down"
        if r.returncode != 0: status["status"] = "degraded"
    except:
        status["checks"]["gateway"] = "unknown"
    
    # Check coordinator DB
    db = HERMES / "coordinator.db"
    if db.is_file():
        try:
            import sqlite3
            conn = sqlite3.connect(str(db), timeout=3)
            conn.execute("SELECT 1").fetchone()
            conn.close()
            status["checks"]["coordinator_db"] = "ok"
        except:
            status["checks"]["coordinator_db"] = "error"
            status["status"] = "degraded"
    else:
        status["checks"]["coordinator_db"] = "missing"
        status["status"] = "degraded"
    
    # Check last prospector tick
    ticks = Path.home() / "Documents/code/prospector/store/scheduler/ticks.jsonl"
    if ticks.is_file():
        try:
            lines = ticks.read_text().splitlines()
            if lines:
                last = json.loads(lines[-1])
                last_ts = last.get("ts", "")
                status["checks"]["prospector_last_tick"] = last_ts[:19] if last_ts else "unknown"
                if last.get("error"):
                    status["checks"]["prospector_status"] = "failing"
                else:
                    status["checks"]["prospector_status"] = "ok"
        except:
            status["checks"]["prospector_status"] = "error"
    
    status["healthy"] = status["status"] == "ok"
    return status

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/health", "/"):
            status = get_estate_status()
            code = 200 if status["healthy"] else 503
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(status, indent=2).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # silent

def main():
    import argparse
    p = argparse.ArgumentParser(description="Health check HTTP endpoint")
    p.add_argument("--port", type=int, default=8699)
    args = p.parse_args()
    server = HTTPServer(("127.0.0.1", args.port), HealthHandler)
    print(f"Health endpoint listening on http://127.0.0.1:{args.port}/health")
    try: server.serve_forever()
    except KeyboardInterrupt: server.shutdown()

if __name__ == "__main__": main()
