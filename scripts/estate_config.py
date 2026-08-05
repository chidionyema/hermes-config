#!/usr/bin/env python3
"""
estate_config.py — Universal estate model loader.

Reads ~/.hermes/estate.yaml and provides typed access to projects,
infrastructure, AI providers, operators, and health checks.
Zero code changes to add a new project — just edit the YAML.
"""
import os, yaml
from pathlib import Path
from typing import List, Dict, Any, Optional

HERMES = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
CONFIG_PATH = HERMES / "estate.yaml"

DEFAULT_CONFIG = {
    "estate": {
        "name": "My Estate",
        "projects": [],
        "infrastructure": [],
        "ai_providers": [],
        "operators": [{"name": "Admin", "telegram_id": "", "role": "admin"}],
        "settings": {
            "daily_digest_time": "09:00",
            "auto_pause_on_moat_failure": True,
            "moat_failure_threshold": 5,
            "notification_channel": "telegram",
        }
    }
}

def load_config() -> dict:
    """Load estate.yaml, creating default if missing."""
    if not CONFIG_PATH.is_file():
        return DEFAULT_CONFIG
    try:
        with open(CONFIG_PATH) as f:
            return yaml.safe_load(f) or DEFAULT_CONFIG
    except Exception:
        return DEFAULT_CONFIG

def save_config(config: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

def get_projects() -> List[dict]:
    return load_config().get("estate", {}).get("projects", [])

def get_infrastructure() -> List[dict]:
    return load_config().get("estate", {}).get("infrastructure", [])

def get_providers() -> List[dict]:
    return load_config().get("estate", {}).get("ai_providers", [])

def get_operators() -> List[dict]:
    return load_config().get("estate", {}).get("operators", [])

def get_setting(key: str, default=None):
    return load_config().get("estate", {}).get("settings", {}).get(key, default)

def add_project(name: str, repo: str, health_checks: list = None, dependencies: list = None):
    config = load_config()
    config["estate"]["projects"].append({
        "name": name, "repo": repo,
        "health_checks": health_checks or [{"type": "git_status"}],
        "dependencies": dependencies or [],
    })
    save_config(config)

def add_infrastructure(name: str, infra_type: str, health_checks: list = None):
    config = load_config()
    config["estate"]["infrastructure"].append({
        "name": name, "type": infra_type,
        "health_checks": health_checks or [{"type": "tcp_connect", "host": "localhost"}],
    })
    save_config(config)

# ── Pluggable health checks ──

def run_health_check(check: dict) -> dict:
    """Run a single health check. Returns {status: pass|fail|error, detail: str}."""
    check_type = check.get("type", "")
    try:
        if check_type == "git_status":
            import subprocess
            repo = Path(check.get("repo", ".")).expanduser()
            r = subprocess.run(["git", "-C", str(repo), "status", "--short"],
                              capture_output=True, text=True, timeout=10)
            dirty = len([l for l in (r.stdout or "").splitlines() if l.strip()])
            return {"status": "pass" if dirty == 0 else "fail",
                    "detail": f"clean" if dirty == 0 else f"dirty({dirty})"}
        
        elif check_type == "process":
            import subprocess
            pattern = check.get("pattern", "")
            r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, timeout=5)
            return {"status": "pass" if r.returncode == 0 else "fail",
                    "detail": "running" if r.returncode == 0 else "not running"}
        
        elif check_type == "tcp_connect":
            import socket
            host = check.get("host", "localhost")
            port = int(check.get("port", 80))
            timeout = float(check.get("timeout", 5))
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            sock.close()
            return {"status": "pass" if result == 0 else "fail",
                    "detail": f"{host}:{port} reachable" if result == 0 else f"{host}:{port} refused"}
        
        elif check_type == "http_endpoint":
            import urllib.request
            url = check.get("url", "")
            timeout = float(check.get("timeout", 10))
            req = urllib.request.Request(url, method="HEAD")
            urllib.request.urlopen(req, timeout=timeout)
            return {"status": "pass", "detail": f"{url} responds"}
        
        elif check_type == "log_check":
            path = Path(check.get("path", "")).expanduser()
            error_pattern = check.get("error_pattern", "ERROR|FATAL")
            if not path.is_file():
                return {"status": "error", "detail": f"log missing: {path}"}
            import re
            content = path.read_text()
            errors = len(re.findall(error_pattern, content))
            return {"status": "pass" if errors == 0 else "fail",
                    "detail": f"{errors} matches of '{error_pattern}'"}
        
        elif check_type == "disk_usage":
            import shutil
            path = Path(check.get("path", "/")).expanduser()
            usage = shutil.disk_usage(path)
            pct = usage.used / usage.total * 100
            threshold = float(check.get("threshold", 90))
            return {"status": "pass" if pct < threshold else "fail",
                    "detail": f"{pct:.1f}% used ({usage.free // 1024**3}GB free)"}
        
        elif check_type == "api_key_valid":
            env_var = check.get("env_var", "")
            return {"status": "pass" if os.getenv(env_var) else "fail",
                    "detail": f"{env_var} is set" if os.getenv(env_var) else f"{env_var} not set"}
        
        elif check_type == "credit_balance":
            # Best-effort: check for recent credit errors in error log
            error_log = HERMES / "logs" / "errors.log"
            if not error_log.is_file():
                return {"status": "pass", "detail": "no error log to check"}
            import re
            content = error_log.read_text()
            credit_errors = len(re.findall(r"credit balance is too low|usage limit reached", content, re.I))
            return {"status": "pass" if credit_errors == 0 else "fail",
                    "detail": f"{credit_errors} credit-related errors in log"}
        
        else:
            return {"status": "error", "detail": f"unknown check type: {check_type}"}
    
    except Exception as e:
        return {"status": "error", "detail": str(e)[:100]}

def run_project_checks(project: dict) -> dict:
    """Run all health checks for a project."""
    results = []
    for check in project.get("health_checks", []):
        check["repo"] = check.get("repo", project.get("repo", "."))
        result = run_health_check(check)
        result["check_type"] = check.get("type", "?")
        results.append(result)
    healthy = all(r["status"] == "pass" for r in results)
    return {"project": project.get("name", "?"), "healthy": healthy, "checks": results}

def run_all_checks() -> dict:
    """Run health checks for all configured projects and infrastructure."""
    config = load_config().get("estate", {})
    results = {"estate": config.get("name", "?"), "projects": [], "infrastructure": []}
    for proj in config.get("projects", []):
        results["projects"].append(run_project_checks(proj))
    for infra in config.get("infrastructure", []):
        results["infrastructure"].append(run_project_checks(infra))
    return results

def setup_wizard():
    """Interactive setup: 5 questions, generates estate.yaml."""
    print("🏗  Otto Setup Wizard\n")
    name = input("Estate name [My Estate]: ").strip() or "My Estate"
    tg = input("Your Telegram chat ID: ").strip()
    repo = input("Project repo path [~/code]: ").strip() or "~/code"
    
    config = DEFAULT_CONFIG
    config["estate"]["name"] = name
    config["estate"]["operators"][0]["telegram_id"] = tg
    if repo:
        config["estate"]["projects"].append({
            "name": "main-project", "repo": repo,
            "health_checks": [{"type": "git_status"}, {"type": "process", "pattern": "main"}],
        })
    
    save_config(config)
    print(f"\n✅ Estate '{name}' configured. Config saved to {CONFIG_PATH}")
    print("   Run `otto setup` to add more projects later.")
    return config

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Estate config manager")
    p.add_argument("--setup", action="store_true", help="Run setup wizard")
    p.add_argument("--check", action="store_true", help="Run all health checks")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    
    if args.setup:
        result = setup_wizard()
    elif args.check:
        result = run_all_checks()
    else:
        result = {"config": load_config()}
    
    if args.json:
        import json
        print(json.dumps(result, indent=2, default=str))
    elif args.check:
        for proj in result.get("projects", []):
            status = "🟢" if proj["healthy"] else "🔴"
            print(f"{status} {proj['project']}: {len(proj['checks'])} checks")
    else:
        import json
        print(json.dumps(result, indent=2, default=str))
