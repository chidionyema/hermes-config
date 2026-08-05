#!/usr/bin/env python3
"""
platform_bridge.py — Future-proofing layer: LLM abstraction + multi-estate + performance.

Makes Otto independent of specific AI providers and deployable anywhere.
"""
import json, os, sys, time
from pathlib import Path
from datetime import datetime, timezone

HERMES = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))

# ── LLM Abstraction ──

PROVIDER_REGISTRY = {
    "anthropic": {"api": "anthropic", "models": ["claude-sonnet-4", "claude-opus-4", "claude-haiku-4"]},
    "openai": {"api": "openai", "models": ["gpt-4o", "gpt-4o-mini"]},
    "minimax": {"api": "minimax", "models": ["MiniMax-M3"]},
    "deepseek": {"api": "deepseek", "models": ["deepseek-v4"]},
    "cursor_cli": {"api": "cursor_cli", "models": ["default"]},
    "ollama": {"api": "ollama", "models": ["llama3", "mistral"]},
}

def get_available_providers():
    """Return providers that are configured and available."""
    available = []
    for name, info in PROVIDER_REGISTRY.items():
        if _provider_configured(name):
            available.append({"name": name, "api": info["api"], "models": info["models"]})
    return available

def _provider_configured(name):
    secrets = HERMES / "secrets.age"
    if name == "anthropic" and os.getenv("ANTHROPIC_API_KEY"): return True
    if name == "openai" and os.getenv("OPENAI_API_KEY"): return True
    if name == "cursor_cli": return True  # uses local CLI
    if name == "ollama":
        import subprocess
        r = subprocess.run(["curl", "-s", "http://localhost:11434/api/tags"], capture_output=True, timeout=3)
        return r.returncode == 0
    # Check secrets manager
    try:
        sys.path.insert(0, str(HERMES / "scripts"))
        from secrets_manager import get_secret
        return bool(get_secret(f"{name}-api-key"))
    except: pass
    return False

def provider_health_check(provider_name):
    """Quick health check for a provider. Returns {healthy, detail}."""
    if provider_name == "cursor_cli":
        import subprocess
        r = subprocess.run(["cursor", "--version"], capture_output=True, timeout=5)
        return {"healthy": r.returncode == 0, "detail": r.stdout.strip()[:50] or "installed"}
    if provider_name == "ollama":
        import subprocess
        r = subprocess.run(["curl", "-s", "http://localhost:11434/api/tags"], capture_output=True, timeout=3)
        return {"healthy": r.returncode == 0, "detail": "responding" if r.returncode == 0 else "down"}
    if provider_name == "anthropic":
        return {"healthy": bool(os.getenv("ANTHROPIC_API_KEY")), "detail": "key configured" if os.getenv("ANTHROPIC_API_KEY") else "no key"}
    return {"healthy": False, "detail": "unknown provider"}

# ── Multi-Estate Namespace ──

def list_estates():
    """Discover estate configs. Currently single-estate, ready for multi-tenant."""
    configs = []
    if (HERMES / "estate.yaml").is_file():
        try:
            import yaml
            cfg = yaml.safe_load((HERMES / "estate.yaml").read_text())
            configs.append({"name": cfg.get("estate", {}).get("name", "default"), "path": str(HERMES / "estate.yaml")})
        except: pass
    # Future: scan estates/ directory for multi-tenant
    estates_dir = HERMES / "estates"
    if estates_dir.is_dir():
        for f in estates_dir.glob("*.yaml"):
            try:
                import yaml
                cfg = yaml.safe_load(f.read_text())
                configs.append({"name": cfg.get("estate", {}).get("name", f.stem), "path": str(f)})
            except: pass
    return configs

# ── Performance Benchmarks ──

def run_benchmarks():
    """Measure panel render times and report latency profile."""
    sys.path.insert(0, str(HERMES / "hermes-agent"))
    results = {}
    panels = [
        ("mission", "gateway.operator_shell.mission", "render_mission_card"),
        ("status", "gateway.operator_shell.status_summary", "render_status_summary"),
        ("prospector", "gateway.operator_shell.prospector_daemon", "render_prospector_daemon"),
        ("commands", "gateway.operator_shell.command_palette", "render_commands"),
    ]
    for name, mod, fn in panels:
        try:
            m = __import__(mod, fromlist=[fn])
            t0 = time.time()
            getattr(m, fn)()
            ms = (time.time() - t0) * 1000
            results[name] = {"latency_ms": round(ms, 1), "status": "pass" if ms < 500 else "slow"}
        except Exception as e:
            results[name] = {"error": str(e)[:80]}
    
    # Compute SLA profile
    latencies = [v["latency_ms"] for v in results.values() if "latency_ms" in v]
    avg = sum(latencies) / max(len(latencies), 1)
    p95 = sorted(latencies)[int(len(latencies) * 0.95)] if len(latencies) > 1 else avg
    
    return {
        "panels": results,
        "avg_ms": round(avg, 1),
        "p95_ms": round(p95, 1),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

# ── Migration Import ──

def import_from_pagerduty(api_key, service_id):
    """Stub: import incidents from PagerDuty API."""
    return {"imported": 0, "status": "PagerDuty import requires API access. Contact support."}

def import_from_datadog(api_key, app_key):
    """Stub: import monitors from Datadog."""
    return {"imported": 0, "status": "Datadog import requires API access. Contact support."}

def main():
    import argparse
    p = argparse.ArgumentParser(description="Platform bridge")
    sp = p.add_subparsers(dest="cmd")
    sp.add_parser("providers"); sp.add_parser("estates"); sp.add_parser("benchmarks")
    sp.add_parser("health")
    args = p.parse_args()
    if args.cmd == "providers": print(json.dumps(get_available_providers(), indent=2))
    elif args.cmd == "estates": print(json.dumps(list_estates(), indent=2))
    elif args.cmd == "benchmarks": print(json.dumps(run_benchmarks(), indent=2))
    elif args.cmd == "health":
        checks = {p: provider_health_check(p) for p in ["cursor_cli", "ollama", "anthropic"]}
        print(json.dumps(checks, indent=2))
    else:
        print(json.dumps({"providers": len(get_available_providers()),
                          "estates": len(list_estates()),
                          "benchmarks": "run --benchmarks"}, indent=2))

if __name__ == "__main__": main()
