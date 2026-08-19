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

The default check reads the credential, which is static and cheap. It cannot see the BALANCE
behind that credential: a key with no credit still reads as present.

Measured 2026-08-19 on prospector-hermes. The default check printed

    provider-chain OK: every configured provider can authenticate here.

at the same moment every call to that provider returned

    HTTP 429: Token Plan usage limit reached: Upgrade your Token Plan or purchase Credits (2056)

THE SECOND CLASS: a health check that proves a credential EXISTS and calls that OK. It is the
same defect prospector wrote down as `models-probe-proves-the-key-not-the-balance`. A key string
is not a brain.

`--probe` spends one minimal completion per provider and answers the question that matters --
can this link buy a token right now. `--alert` sends the verdict straight to Telegram via
estate_alert when NO link is live, deliberately bypassing the gateway queue: the queue is drained
by agent jobs, so routing "the brain is dead" through it needs the brain that is dead.

Exit 0 = the chain has a live brain (or, without --probe, every link can authenticate).
Exit 1 = it does not.
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


# --- probe mode ----------------------------------------------------------------------------
# One minimal completion per provider. The point is the BALANCE, not the key, so the
# classification below is the whole value of this block:
#
#   LIVE            the call returned a completion
#   NO_CREDIT       authenticated and refused for money (402, or 429 whose body names credit,
#                   balance, quota or a token plan). This is the one that reads as healthy
#                   everywhere else in the estate.
#   RATE_LIMITED    429 with no credit language -- transient, retry works, do not tell the
#                   founder to buy anything
#   BAD_CREDENTIAL  401 / 403
#   NO_MODEL        404 on the model id (the key is fine, the model name has moved on)
#   UNREACHABLE     DNS, TLS, timeout. Never reported as NO_CREDIT: a dropped wifi link must
#                   not send the founder to a billing page.
#   NO_PROBE        this script does not know how to call that provider

_CREDIT_WORDS = (
    "credit", "balance", "quota", "token plan", "usage limit", "insufficient",
    "payment required", "billing", "free trial", "depleted", "exceeded your current quota",
)

_DEFAULT_MODELS = {
    "minimax": "MiniMax-M3",
    "anthropic": "claude-haiku-4-5-20251001",
    "gemini": "gemini-3.6-flash",
    "deepseek": "deepseek-chat",
    "openai": "gpt-4o-mini",
}


def _provider_base_url(cfg: dict, provider: str, role: str) -> str:
    """base_url the agent would actually use for this link, or '' for the vendor default."""
    if role == "primary":
        m = cfg.get("model")
        if isinstance(m, dict) and m.get("base_url"):
            return str(m["base_url"]).rstrip("/")
    provs = cfg.get("providers")
    if isinstance(provs, dict):
        entry = provs.get(provider)
        if isinstance(entry, dict) and entry.get("base_url"):
            return str(entry["base_url"]).rstrip("/")
    return ""


def _probe_request(provider: str, model: str, key: str, base: str):
    """Build (url, headers, body) for one minimal completion, or None if unprobeable."""
    if provider in ("minimax", "anthropic"):
        # MiniMax speaks the Anthropic wire format at its /anthropic base_url.
        root = base or ("https://api.minimax.io/anthropic" if provider == "minimax"
                        else "https://api.anthropic.com")
        return (
            root + "/v1/messages",
            {"Content-Type": "application/json", "anthropic-version": "2023-06-01",
             **({"Authorization": "Bearer " + key} if provider == "minimax"
                else {"x-api-key": key})},
            {"model": model, "max_tokens": 8, "messages": [{"role": "user", "content": "hi"}]},
        )
    if provider in ("deepseek", "openai"):
        root = base or ("https://api.deepseek.com" if provider == "deepseek"
                        else "https://api.openai.com/v1")
        return (
            root + "/chat/completions",
            {"Content-Type": "application/json", "Authorization": "Bearer " + key},
            {"model": model, "max_tokens": 8, "messages": [{"role": "user", "content": "hi"}]},
        )
    if provider == "gemini":
        root = base or "https://generativelanguage.googleapis.com/v1beta"
        return (
            f"{root}/models/{model}:generateContent?key={key}",
            {"Content-Type": "application/json"},
            {"contents": [{"parts": [{"text": "hi"}]}]},
        )
    return None


def _classify(status: int, body: str) -> tuple[str, str]:
    low = body.lower()
    money = any(w in low for w in _CREDIT_WORDS)
    if status == 402 or (status == 429 and money) or (status == 403 and money):
        return "NO_CREDIT", _first_line(body)
    if status == 429:
        return "RATE_LIMITED", _first_line(body)
    if status in (401, 403):
        return "BAD_CREDENTIAL", _first_line(body)
    if status == 404:
        return "NO_MODEL", _first_line(body)
    return "HTTP_%d" % status, _first_line(body)


def _first_line(body: str) -> str:
    """The vendor message, not the whole JSON envelope, and never more than one line."""
    import json as _json
    try:
        d = _json.loads(body)
        for path in (("error", "message"), ("message",), ("error",)):
            cur = d
            for k in path:
                cur = cur.get(k) if isinstance(cur, dict) else None
            if isinstance(cur, str) and cur.strip():
                return " ".join(cur.split())[:200]
    except Exception:
        pass
    return " ".join(body.split())[:200]


def probe_chain(chain: list[dict], cfg: dict, env: dict[str, str] | None = None,
                timeout: float = 30.0) -> list[dict]:
    """Spend one minimal call per link and report whether it can buy a token right now."""
    import urllib.error
    import urllib.request

    env = os.environ if env is None else env
    results = []
    for link in chain:
        name = link["provider"]
        model = link.get("model") or _DEFAULT_MODELS.get(name) or ""
        envs = _key_envs(name) or []
        key = next((env[e] for e in envs if (env.get(e) or "").strip()), "")
        if envs and not key:
            results.append({**link, "verdict": "NO_CREDENTIAL",
                            "detail": f"none of {envs} is set here"})
            continue
        req = _probe_request(name, model, key, _provider_base_url(cfg, name, link["role"]))
        if req is None:
            results.append({**link, "verdict": "NO_PROBE",
                            "detail": "this script cannot call that provider"})
            continue
        url, headers, body = req
        try:
            r = urllib.request.urlopen(
                urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers),
                timeout=timeout,
            )
            r.read()
            results.append({**link, "verdict": "LIVE", "detail": f"HTTP {r.status}, {model}"})
        except urllib.error.HTTPError as e:
            raw = ""
            try:
                raw = e.read().decode(errors="replace")
            except Exception:
                pass
            verdict, detail = _classify(e.code, raw)
            results.append({**link, "verdict": verdict, "detail": f"HTTP {e.code}: {detail}"})
        except Exception as e:
            # Never NO_CREDIT. A dropped link is not a bill.
            results.append({**link, "verdict": "UNREACHABLE",
                            "detail": f"{type(e).__name__}: {str(e)[:120]}"})
    return results


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


def _alert_no_brain(results: list[dict]) -> None:
    """Tell the founder directly that nothing can answer him.

    Deliberately NOT the gateway queue. The queue is drained by `queue-curator` and forwarded by
    `otto-dispatch`, both of which are agent jobs. Routing "there is no brain" through a path that
    needs a brain is how this outage stayed silent: 185 HTTP 429s in gateway.log and the only
    signal the founder ever got was Telegram going quiet.
    """
    sys.path.insert(0, str(HERMES / "scripts"))
    try:
        from estate_alert import send_operator_alert  # type: ignore
    except Exception as exc:  # pragma: no cover - alerting must never mask the verdict
        print(f"provider-chain: cannot load estate_alert ({exc}); verdict still stands")
        return
    lines = [f"{r['provider']} ({r['role']}): {r['verdict']} — {r['detail']}" for r in results]
    send_operator_alert(
        "NO BRAIN. Every configured model provider refused a live call, so the agent cannot "
        "answer anything until one is topped up.\n\n" + "\n".join(lines),
        debounce_key="provider-chain-no-brain",
        # Six hours. The default 300s would repeat a total outage every run of an hourly job,
        # and an alarm the founder learns to scroll past is an alarm that has stopped working.
        debounce_s=6 * 3600,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--config", default=str(HERMES / "config.yaml"))
    ap.add_argument("--probe", action="store_true",
                    help="spend one minimal call per provider and grade the BALANCE, not the key")
    ap.add_argument("--alert", action="store_true",
                    help="with --probe: Telegram the founder directly when no link is live")
    args = ap.parse_args()

    _load_env_file()
    try:
        import yaml  # type: ignore

        cfg = yaml.safe_load(Path(args.config).read_text()) or {}
    except Exception as exc:
        print(f"provider-chain: cannot read {args.config}: {exc}")
        return 1

    chain = chain_from_config(cfg)
    if not chain:
        print("provider-chain BROKEN: no provider is configured at all.")
        return 1

    if args.probe:
        results = probe_chain(chain, cfg)
        live = [r for r in results if r["verdict"] == "LIVE"]
        ok = bool(live)
    else:
        results = check_chain(chain)
        ok = not [r for r in results if r["verdict"] != "OK"]

    if args.json:
        print(json.dumps({"chain": results, "ok": ok, "probed": args.probe}, indent=2))
    else:
        for r in results:
            good = r["verdict"] in ("OK", "LIVE")
            mark = "✅" if good else "❌"
            print(f"{mark} {r['role']:8} {r['provider']:12} {r.get('model') or '-':24} "
                  f"{r['verdict']:14} {r['detail']}")
        if args.probe and not ok:
            print("\nNO BRAIN: not one configured provider answered a live call.")
            print("A key that is present is not a key that can buy a token. Top one up, or the")
            print("agent stays silent — it has no fallback to walk.")
        elif args.probe:
            print(f"\nprovider-chain LIVE: {len(live)}/{len(results)} link(s) answered a real call.")
        elif not ok:
            names = ", ".join(r["provider"] for r in results if r["verdict"] != "OK")
            print(f"\nprovider-chain BROKEN: {names} cannot authenticate here.")
            print("A dead link does not soften a failure, it renames it: the run still fails and")
            print("the error text blames a provider nobody configured. Remove it or give it a key.")
        else:
            print("\nprovider-chain OK: every configured provider can authenticate here.")
            print("This says nothing about BALANCE. Run --probe for the answer that matters.")

    if args.alert and args.probe and not ok:
        _alert_no_brain(results)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
