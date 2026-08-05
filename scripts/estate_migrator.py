#!/usr/bin/env python3
"""estate_migrator.py — Migrate hardcoded projects to estate.yaml."""
import json, os, sys, subprocess
from pathlib import Path
HERMES = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))

KNOWN_PROJECTS = [
    {"name": "prospector", "repo": "~/Documents/code/prospector",
     "health_checks": [{"type": "process", "pattern": "prospector.scheduler"},
                       {"type": "log_check", "path": "~/Documents/code/prospector/store/scheduler/ticks.jsonl", "error_pattern": "\"error\": \""}],
     "dependencies": ["cursor_cli", "claude_cli"]},
    {"name": "signal-engine", "repo": "~/Documents/code/signal-engine",
     "health_checks": [{"type": "process", "pattern": "signal.engine"}],
     "dependencies": ["tcc_permission", "exchange_api"]},
    {"name": "hermes", "repo": "~/.hermes/hermes-agent",
     "health_checks": [{"type": "process", "pattern": "gateway.run"},
                       {"type": "process", "pattern": "coordinator"},
                       {"type": "log_check", "path": "~/.hermes/logs/errors.log", "error_pattern": "CRITICAL|FATAL"}],
     "dependencies": ["telegram_api", "anthropic_api"]},
]

AI_PROVIDERS = [
    {"name": "anthropic", "type": "anthropic", "health_checks": [{"type": "credit_balance"}]},
    {"name": "cursor_cli", "type": "cursor_cli", "health_checks": [{"type": "api_key_valid", "env_var": "CURSOR_API_KEY"}]},
]

def discover_projects():
    """Scan for known projects and return only those that exist."""
    found = []
    for proj in KNOWN_PROJECTS:
        repo = Path(proj["repo"]).expanduser()
        if repo.is_dir():
            proj["repo"] = str(repo)
            found.append(proj)
    return found

def generate_config(dry_run=False):
    projects = discover_projects()
    config = {
        "estate": {
            "name": "My Estate",
            "projects": projects,
            "ai_providers": AI_PROVIDERS,
            "infrastructure": [],
            "operators": [{"name": "Admin", "telegram_id": "", "role": "admin"}],
            "alerting": {
                "channels": {"telegram": {"enabled": True}},
                "routing": {"info": ["telegram"], "warning": ["telegram"], "error": ["telegram"], "critical": ["telegram"]}
            },
            "settings": {"daily_digest_time": "09:00", "auto_pause_on_moat_failure": True, "moat_failure_threshold": 5}
        }
    }
    if not dry_run:
        try:
            import yaml
            path = HERMES / "estate.yaml"
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w") as f:
                yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
        except ImportError:
            # Write JSON as fallback
            path = HERMES / "estate.yaml"
            path.write_text(json.dumps(config, indent=2))
    return {"projects_found": len(projects), "projects": [p["name"] for p in projects], "dry_run": dry_run}

def main():
    import argparse
    p = argparse.ArgumentParser(description="Estate migrator")
    p.add_argument("--migrate", action="store_true"); p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    dry = args.dry_run or not args.migrate
    r = generate_config(dry_run=dry)
    if args.json: print(json.dumps(r, indent=2))
    else: print(f"Projects found: {r['projects_found']} — {', '.join(r['projects'])}" + (" (dry-run)" if dry else " — estate.yaml written"))

if __name__ == "__main__": main()
