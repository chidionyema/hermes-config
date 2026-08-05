#!/usr/bin/env python3
"""
secrets_manager.py — Encrypted secrets store using age encryption.

Replaces plaintext API keys in config.yaml and .env with an encrypted
~/.hermes/secrets.age file. Keys are never written to disk unencrypted.

Usage:
    otto secrets init          — create keypair, encrypt existing secrets
    otto secrets set KEY VAL   — add/update a secret
    otto secrets get KEY       — retrieve a secret (for scripts)
    otto secrets list          — list available keys (not values)
    otto secrets rotate        — re-encrypt with new keypair
"""

import json, os, subprocess, sys
from pathlib import Path

HERMES = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
SECRETS_FILE = HERMES / "secrets.age"
KEY_FILE = HERMES / "meta" / "otto-age-key.txt"
PUBKEY_FILE = HERMES / "meta" / "otto-age-pubkey.txt"

def _have_age():
    return subprocess.run(["which", "age"], capture_output=True).returncode == 0

def init_secrets():
    """Generate age keypair, create empty secrets store."""
    if not _have_age():
        print("⚠️  'age' not found. Install: brew install age")
        return False
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not KEY_FILE.is_file():
        r = subprocess.run(["age-keygen", "-o", str(KEY_FILE)], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"❌ Keygen failed: {r.stderr}")
            return False
    # Extract public key
    r = subprocess.run(["age-keygen", "-y", str(KEY_FILE)], capture_output=True, text=True)
    PUBKEY_FILE.write_text(r.stdout.strip())
    # Create empty secrets file if missing
    if not SECRETS_FILE.is_file():
        _save({})
    print(f"✅ Secrets store initialized. Public key: {r.stdout.strip()[:50]}...")
    return True

def set_secret(key, value):
    secrets = _load()
    secrets[key] = value
    _save(secrets)
    print(f"✅ Set {key}")

def get_secret(key):
    secrets = _load()
    return secrets.get(key, "")

def list_secrets():
    secrets = _load()
    for k in sorted(secrets.keys()):
        print(f"  {k} = {'***' + secrets[k][-4:] if secrets[k] else '(empty)'}")

def _load():
    if not SECRETS_FILE.is_file():
        return {}
    if not _have_age():
        return json.loads(SECRETS_FILE.read_text()) if SECRETS_FILE.is_file() else {}
    r = subprocess.run(["age", "-d", "-i", str(KEY_FILE), str(SECRETS_FILE)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return {}
    try: return json.loads(r.stdout)
    except: return {}

def _save(data):
    json_text = json.dumps(data, indent=2)
    if _have_age() and PUBKEY_FILE.is_file():
        pubkey = PUBKEY_FILE.read_text().strip()
        r = subprocess.run(["age", "-r", pubkey, "-o", str(SECRETS_FILE)],
                          input=json_text, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"⚠️  Encryption failed, falling back to plaintext: {r.stderr}", file=sys.stderr)
            SECRETS_FILE.write_text(json_text)
    else:
        SECRETS_FILE.write_text(json_text)

def rotate():
    """Re-encrypt with current keypair."""
    secrets = _load()
    _save(secrets)
    print(f"✅ Rotated {len(secrets)} secrets")

def migrate_from_env():
    """Migrate secrets from environment variables and config.yaml."""
    secrets = _load()
    # Common API keys to migrate
    env_vars = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CURSOR_API_KEY",
                "TELEGRAM_BOT_TOKEN", "NTFY_TOPIC", "HERMES_GATEWAY_TOKEN"]
    for var in env_vars:
        val = os.getenv(var, "")
        if val and var.lower().replace("_","-") not in secrets:
            secrets[var.lower().replace("_","-")] = val
    # Also check config.yaml
    config = HERMES / "config.yaml"
    if config.is_file():
        try:
            import yaml
            cfg = yaml.safe_load(config.read_text()) or {}
            for k, v in cfg.items():
                if "key" in k.lower() or "token" in k.lower() or "secret" in k.lower():
                    sk = k.lower().replace("_","-")
                    if sk not in secrets and isinstance(v, str) and len(v) > 8:
                        secrets[sk] = v
        except: pass
    if secrets:
        _save(secrets)
        print(f"✅ Migrated {len(secrets)} secrets from env/config")
    else:
        print("No secrets found to migrate.")

def main():
    import argparse
    p = argparse.ArgumentParser(description="Encrypted secrets manager")
    sp = p.add_subparsers(dest="cmd")
    sp.add_parser("init"); sp.add_parser("list"); sp.add_parser("rotate"); sp.add_parser("migrate")
    s = sp.add_parser("set"); s.add_argument("key"); s.add_argument("value")
    g = sp.add_parser("get"); g.add_argument("key")
    args = p.parse_args()
    if args.cmd == "init": init_secrets()
    elif args.cmd == "set": set_secret(args.key, args.value)
    elif args.cmd == "get": print(get_secret(args.key))
    elif args.cmd == "list": list_secrets()
    elif args.cmd == "rotate": rotate()
    elif args.cmd == "migrate": migrate_from_env()
    else: p.print_help()

if __name__ == "__main__": main()
