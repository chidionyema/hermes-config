#!/usr/bin/env python3
"""alert_router.py — Multi-channel alert routing. Telegram, email, Slack, webhook, PagerDuty."""
import json, os, sys, smtplib, urllib.request
from email.mime.text import MIMEText
from datetime import datetime, timezone
from pathlib import Path

HERMES = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
CONFIG_PATH = HERMES / "estate.yaml"
ALERT_LOG = HERMES / "logs" / "alert-router.jsonl"

DEFAULT_ROUTING = {"info": ["telegram"], "warning": ["telegram"], "error": ["telegram"], "critical": ["telegram"]}

def _load_config():
    try:
        import yaml
        if CONFIG_PATH.is_file():
            with open(CONFIG_PATH) as f: return yaml.safe_load(f) or {}
    except: pass
    return {}

def _routing():
    cfg = _load_config()
    return cfg.get("estate", {}).get("alerting", {}).get("routing", DEFAULT_ROUTING)

def _channels():
    cfg = _load_config()
    return cfg.get("estate", {}).get("alerting", {}).get("channels", {"telegram": {"enabled": True}})

def send_alert(message, severity="warning"):
    routing = _routing()
    channels = _channels()
    targets = routing.get(severity, routing.get("warning", ["telegram"]))
    results = {}
    for target in targets:
        ch = channels.get(target, {})
        if not ch.get("enabled", True): continue
        try:
            if target == "telegram":
                subprocess.run(["hermes", "send", "--to", "telegram", message], capture_output=True, timeout=10)
                results[target] = "sent"
            elif target == "slack" and ch.get("webhook_url"):
                _send_slack(ch["webhook_url"], message, severity)
                results[target] = "sent"
            elif target == "email" and ch.get("smtp_host"):
                _send_email(ch, message, severity)
                results[target] = "sent"
            elif target == "webhook" and ch.get("url"):
                _send_webhook(ch["url"], message, severity)
                results[target] = "sent"
            else:
                results[target] = "not_configured"
        except Exception as e:
            results[target] = f"failed: {str(e)[:50]}"
    _log(severity, message, results)
    return results

def _send_slack(url, message, severity):
    colors = {"info": "#36a64f", "warning": "#ffcc00", "error": "#ff0000", "critical": "#ff0000"}
    data = json.dumps({"attachments": [{"color": colors.get(severity,"#cccccc"), "text": message}]}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10)

def _send_email(ch, message, severity):
    msg = MIMEText(message); msg["Subject"] = f"[{severity.upper()}] Otto Alert"
    msg["From"] = ch.get("from", "otto@localhost"); msg["To"] = ch.get("to", "")
    with smtplib.SMTP(ch["smtp_host"], int(ch.get("smtp_port", 587)), timeout=10) as s:
        s.starttls(); s.login(ch.get("smtp_user",""), ch.get("smtp_pass","")); s.send_message(msg)

def _send_webhook(url, message, severity):
    data = json.dumps({"text": message, "severity": severity, "timestamp": datetime.now(timezone.utc).isoformat()}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10)

def _log(severity, message, results):
    ALERT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(ALERT_LOG, "a") as f:
        f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "severity": severity, "message": message[:200], "results": results}) + "\n")

import subprocess
def main():
    import argparse
    p = argparse.ArgumentParser(description="Alert router")
    p.add_argument("--test", action="store_true", help="Send test alert")
    p.add_argument("--channels", action="store_true", help="List configured channels")
    p.add_argument("--severity", default="info"); p.add_argument("--message", default="Test alert from Otto")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    if args.test: r = send_alert(args.message, args.severity)
    elif args.channels:
        r = {"channels": _channels(), "routing": _routing()}
    else: r = {"channels": _channels(), "routing": _routing()}
    if args.json: print(json.dumps(r, indent=2, default=str))
    else: print(json.dumps(r, indent=2, default=str))

if __name__ == "__main__": main()
