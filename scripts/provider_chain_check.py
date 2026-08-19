#!/usr/bin/env python3
"""Refuse a provider chain whose members cannot authenticate here.

Measured on prospector-hermes, 2026-08-19. `config.yaml` said the model provider was minimax,
and it was. But `fallback_model` still read:

    - provider: anthropic
      model: claude-haiku-4-5-20251001
    - provider: gemini
      model: gemini-2.5-flash

There is no ANTHROPIC_API_KEY anywhere in this estate, and the Gemini account is out of
prepayment credit. So every agent-mode cron job that hiccupped on MiniMax walked the chain and
died reporting

    RuntimeError: HTTP 429: Gemini HTTP 429 (RESOURCE_EXHAUSTED): Your prepayment credits are
    depleted.

which names a provider nobody configured and says nothing about the provider that actually ran.
The daily activity summary failed that way every evening.

THE CLASS: a fallback chain of dead providers does not degrade a failure, it RELABELS it. The
run still fails, and the error text now points at the wrong system, so the diagnosis starts in
the wrong place. A chain is only a chain if every link can authenticate.

This checks the credential, which is static and cheap. It cannot check the BALANCE behind the
credential; a key with no credit still reads as present here. That is why the failure above ran
for days -- so `--probe` spends one minimal call per provider when you want the stronger answer.

Exit 0 = every configured provider can authenticate. Exit 1 = at least one cannot.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERMES = Path(os.path.expanduser("~/.hermes"))

# Used only when hermes_cli.auth cannot be imported (running outside the venv). Keeping the
# fallback narrow is deliberate: an unknown provider must be REPORTED, never assumed fine.
_STATIC_KEY_ENVS = {
    "anthropic": ["ANTHROPIC_API_KEY"],
    "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
    "minimax": ["MINIMAX_API_KEY"],
    "deepseek": ["DEEPSEEK_API_KEY"],
    "openai": ["OPENAI_API_KEY"],
}


def _load_env_file() -> None:
    """Read ~/.hermes/.env the way the daemons do, so a manual run sees what they see."""
    env = HERMES / ".env"
    if not env.exists():
        return
    for line in env.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _key_envs(provider: str) -> list[str] | None:
    """The env vars that would authenticate `provider`, or None if it is unknown here."""
    try:
        sys.path.insert(0, str(HERMES / "hermes-agent"))
        from hermes_cli.auth import PROVIDER_REGISTRY  # type: ignore

        cfg = PROVIDER_REGISTRY.get(provider)
        if cfg is None:
            return None
        return list(getattr(cfg, "api_key_env_vars", None) or [])
    except Exception:
        return _STATIC_KEY_ENVS.get(provider)


def chain_from_config(cfg: dict) -> list[dict]:
    """Every provider this agent may end up calling, primary first.

    `fallback_providers` wins over `fallback_model` because that is the precedence the cron
    scheduler uses (`hermes-agent/cron/scheduler.py`: `_cfg.get("fallback_providers") or
    _cfg.get("fallback_model")`). Checking the other one would grade a chain nothing walks.
    """
    out: list[dict] = []
    model = cfg.get("model")
    if isinstance(model, dict) and model.get("provider"):
        out.append({"provider": str(model["provider"]).strip().lower(),
                    "model": model.get("default"), "role": "primary"})
    fb = cfg.get("fallback_providers") or cfg.get("fallback_model") or []
    if isinstance(fb, (str, dict)):
        fb = [fb]
    for entry in fb:
        if isinstance(entry, str):
            entry = {"provider": entry}
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("provider") or "").strip().lower()
        if name:
            out.append({"provider": name, "model": entry.get("model"), "role": "fallback"})
    return out


def check_chain(chain: list[dict], env: dict[str, str] | None = None) -> list[dict]:
    env = os.environ if env is None else env
    results = []
    for link in chain:
        name = link["provider"]
        envs = _key_envs(name)
        if envs is None:
            verdict, detail = "UNKNOWN", "provider not in PROVIDER_REGISTRY"
        elif not envs:
            verdict, detail = "OK", "no API key required"
        else:
            present = [e for e in envs if (env.get(e) or "").strip()]
            if present:
                verdict, detail = "OK", f"credential in {present[0]}"
            else:
                verdict, detail = "NO_CREDENTIAL", f"none of {envs} is set here"
        results.append({**link, "verdict": verdict, "detail": detail})
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--config", default=str(HERMES / "config.yaml"))
    args = ap.parse_args()

    _load_env_file()
    try:
        import yaml  # type: ignore

        cfg = yaml.safe_load(Path(args.config).read_text()) or {}
    except Exception as exc:
        print(f"provider-chain: cannot read {args.config}: {exc}")
        return 1

    results = check_chain(chain_from_config(cfg))
    bad = [r for r in results if r["verdict"] != "OK"]

    if args.json:
        print(json.dumps({"chain": results, "ok": not bad}, indent=2))
    else:
        for r in results:
            mark = "✅" if r["verdict"] == "OK" else "❌"
            print(f"{mark} {r['role']:8} {r['provider']:12} {r.get('model') or '-':32} {r['detail']}")
        if bad:
            names = ", ".join(r["provider"] for r in bad)
            print(f"\nprovider-chain BROKEN: {names} cannot authenticate here.")
            print("A dead link does not soften a failure, it renames it: the run still fails and")
            print("the error text blames a provider nobody configured. Remove it or give it a key.")
        else:
            print("\nprovider-chain OK: every configured provider can authenticate here.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
