#!/usr/bin/env python3
"""route(role, prompt) — per-role provider rotation for the autonomous estate.

Phase 1 of the heavenly-estate design
(~/.hermes/reports/heavenly-estate-architecture-2026-06-20.md, lines 80-82, 124-126).

The 3-role topology, each on a direct provider with a fallback chain (NO OpenRouter):

    coordinator : claude-cli         -> minimax
    strategist  : claude-cli         -> minimax
    executor    : minimax            -> claude-cli

(That list is a summary and WILL go stale — ROLE_CHAINS below is the truth, and
routing.json overrides even that. It is repeated here only because a reader
opening this file deserves the shape before the evidence.)

route() tries the chain in order and ROTATES to the next provider on a rate limit
(429), overload/5xx (503/529), timeout, connection failure, or auth/billing error
(a dead-credit provider must fail over, not hard-stop). It RAISES immediately on a
400 BadRequest — rotating providers cannot fix a malformed prompt.

This is the resilience root: with it, one MiniMax 429 no longer freezes the estate
because every role has somewhere to fall over to.

Test seam (mirrors HERMES_FAKE_GATEWAY): set HERMES_ROUTE_FAIL="minimax,anthropic"
to force those providers to raise a simulated 429 before the network call, so a
fallback proof can drive the primary down deterministically while the real fallback
provider still runs live.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field

import httpx

try:
    from openai import (
        OpenAI,
        APIConnectionError,
        APITimeoutError,
        BadRequestError,
        InternalServerError,
        RateLimitError,
        APIStatusError,
    )
except ImportError as e:  # pragma: no cover - environment guard
    sys.stderr.write(f"route.py requires the openai SDK: {e}\n")
    raise


# ── Provider registry ──────────────────────────────────────────────────────────
# transport "openai": OpenAI /chat/completions over HTTP (verified live 2026-06-20
#   against /models for deepseek + minimax).
# transport "cli": a local agent CLI driven headless via subprocess. claude-cli runs
#   on the Claude Code SUBSCRIPTION (OAuth) — we unset ANTHROPIC_API_KEY so it does NOT
#   fall back to the dead pay-per-token API.
PROVIDERS: dict[str, dict] = {
    "deepseek":   {"transport": "openai", "base_url": "https://api.deepseek.com",                              "key_env": "DEEPSEEK_API_KEY"},
    "minimax":    {"transport": "openai", "base_url": "https://api.minimax.io/v1",                             "key_env": "MINIMAX_API_KEY"},
    "anthropic":  {"transport": "openai", "base_url": "https://api.anthropic.com/v1",                          "key_env": "ANTHROPIC_API_KEY"},  # dead credits — kept for re-enable
    "claude-cli": {"transport": "cli", "argv": ["claude", "-p"], "unset_env": ["ANTHROPIC_API_KEY"]},
}

# ── Per-role fallback chains (provider, model), in priority order ───────────────
# Claude Code is primary; MiniMax is the working secondary. Founder direction
# 2026-08-06: this order tracks model price and capability, so it is expected to
# change — override it in ROUTING_OVERRIDE (below) rather than editing this table,
# and NOTHING here needs a code change to re-point.
#
# Every head of every chain was dead on 2026-08-06, measured, not assumed:
#
#   deepseek  GET /models        -> 200          key is valid
#             GET /user/balance  -> {"is_available": false,
#                                    "total_balance": "-0.22"}   CANNOT SERVE
#     A /models probe calls this provider healthy. It authenticates fine and
#     fails every completion. It led the coordinator chain, so the estate paid
#     a guaranteed failure before every single call — 92,292 RouteExhausted
#     rows in coordinator.db, 3,396 in the last 24h alone.
#
#   agy-cli   agy -p 'ping'      -> "Individual quota reached. Please upgrade your
#                                    subscription... Resets in 155h51m58s."
#     RETIRED from the registry entirely on founder instruction 2026-08-06, not
#     merely demoted. A provider left registered is a provider an override file
#     or a future edit can put back at a chain head; the whole point of the
#     92,292-RouteExhausted regression above is that a dead head is invisible
#     because the chain still "works". It is a real binary (~/.local/bin/agy,
#     Mach-O x86_64) — the reason it goes is the quota block, not absence.
#
#   claude-cli was reachable all along; the daemon just could not find it
#     (launchd PATH, see _resolve_cli_binary).
#
#   gemini    GET /models                 -> 200, 14 models listed
#             POST /chat/completions      -> 429 "Your prepayment credits are
#                                            depleted."          CANNOT SERVE
#     The THIRD provider this session whose key authenticates and whose
#     completions cannot run. A /models probe is not a health check — it proves
#     the key, never the balance. Gemini held executor's ONLY fallback seat, so
#     that chain had no survivable second leg at all. RETIRED from the registry
#     on founder instruction 2026-08-06, same call as agy-cli: a provider left
#     registered is one an override file or a careless edit can put back at a
#     chain head, and that is precisely the failure this whole file now exists
#     to make impossible.
#
# That leaves exactly two providers measured able to serve on 2026-08-06:
# claude-cli (subscription) and minimax (metered). Founder direction: Claude
# Code primary, MiniMax secondary.
#
# executor keeps minimax at its head deliberately, and it is NOT a contradiction
# of "Claude Code is primary": executor is the high-volume bulk role, and the
# Claude Code subscription is a shared, rate-limited resource. Spending it on
# bulk execution is how coordinator and strategist — the roles that actually
# need the better brain — get starved. minimax absorbs the volume; claude-cli is
# the fallback that keeps executor alive when it does not.
# CLI providers use model "" = the CLI's own default model.
ROLE_CHAINS: dict[str, list[tuple[str, str]]] = {
    "coordinator": [("claude-cli", ""), ("minimax", "MiniMax-M3")],
    "strategist":  [("claude-cli", ""), ("minimax", "MiniMax-M3")],
    "executor":    [("minimax",    "MiniMax-M3"), ("claude-cli", "")],
}

# Optional operator override, applied over ROLE_CHAINS at import. Exists so the
# routing order can follow model prices without a code edit or a redeploy:
#
#   ~/.hermes/routing.json
#   {"coordinator": [["claude-cli", ""], ["minimax", "MiniMax-M3"]]}
#
# Absent (the normal case) => the literal table above IS the effective routing,
# which keeps estate-audit.py:161 honest — it reads these chains by TEXT PARSE
# and cannot see a dict built at runtime. When an override IS present we say so
# on stderr, because silent re-routing is the same class of bug as a silent
# fallback: the run succeeds and nobody knows which brain answered.
ROUTING_OVERRIDE = os.environ.get(
    "HERMES_ROUTING_FILE", os.path.expanduser("~/.hermes/routing.json")
)


def _apply_routing_override(path: str = ROUTING_OVERRIDE) -> list[str]:
    """Merge the override file into ROLE_CHAINS. Returns the roles it changed."""
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        # Never let a malformed override silently revert routing to the defaults
        # — that is indistinguishable from the file working.
        sys.stderr.write(f"route.py: ignoring unreadable {path}: {e}\n")
        return []
    changed = []
    for role, chain in (raw.items() if isinstance(raw, dict) else []):
        if role not in ROLE_CHAINS:
            sys.stderr.write(f"route.py: {path} names unknown role {role!r} — ignored\n")
            continue
        try:
            parsed = [(str(p), str(m)) for p, m in chain]
        except (TypeError, ValueError):
            sys.stderr.write(f"route.py: {path} role {role!r} is not [[provider, model], …] — ignored\n")
            continue
        unknown = [p for p, _ in parsed if p not in PROVIDERS]
        if unknown:
            sys.stderr.write(f"route.py: {path} role {role!r} names unknown provider(s) {unknown} — ignored\n")
            continue
        if not parsed:
            sys.stderr.write(f"route.py: {path} role {role!r} has an empty chain — ignored\n")
            continue
        ROLE_CHAINS[role] = parsed
        changed.append(role)
    if changed:
        sys.stderr.write(f"route.py: routing overridden from {path} for {sorted(changed)}\n")
    return changed


_apply_routing_override()

CLI_TIMEOUT = float(os.environ.get("HERMES_CLI_TIMEOUT", "300"))  # CLIs slower than raw API; give room (overridable for cost-bounded eval runs)

# Errors that mean "this provider can't serve right now — try the next one."
ROTATE_ON = (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError)

DEFAULT_TIMEOUT = 60.0


class CliError(RuntimeError):
    """A CLI-transport provider failed (non-zero exit, timeout, or error text). Rotatable."""


# Output substrings that mean a CLI "succeeded" (exit 0) but actually hit a provider
# limit — must be treated as a failure so the chain rotates.
_CLI_FAIL_TEXT = ("credit balance is too low", "rate limit", "quota exceeded",
                  "usage limit", "overloaded", "please upgrade")


# Directories a launchd job does NOT get on PATH but where our CLIs actually live.
# launchd hands a daemon PATH=/usr/bin:/bin:/usr/sbin:/sbin — measured on the live
# coordinator (ps eww). `claude` is in ~/.local/bin, so every claude-cli leg raised
# FileNotFoundError -> "claude-cli not installed", which reads like a missing install
# and is really a missing PATH entry. Resolving the binary ourselves means the daemon
# does not depend on how it happened to be launched.
_CLI_EXTRA_PATH = (
    os.path.expanduser("~/.local/bin"),
    "/opt/homebrew/bin",
    "/usr/local/bin",
)


def _resolve_cli_binary(name: str) -> str | None:
    """Absolute path to *name*, searching PATH then the launchd-invisible dirs."""
    found = shutil.which(name)
    if found:
        return found
    return shutil.which(name, path=os.pathsep.join(_CLI_EXTRA_PATH))


def _call_cli(provider: str, cfg: dict, model: str, prompt: str,
              system: str | None, timeout: float) -> str:
    argv = list(cfg["argv"])
    resolved = _resolve_cli_binary(argv[0])
    if resolved is None:
        # Say WHERE we looked. A bare "not installed: claude" sent us hunting for
        # a missing install when the binary was there all along and launchd's PATH
        # (/usr/bin:/bin:/usr/sbin:/sbin) simply could not see it. The searched
        # path is the whole diagnosis.
        searched = os.environ.get("PATH", "") + os.pathsep + os.pathsep.join(_CLI_EXTRA_PATH)
        raise CliError(f"{provider} not installed: {argv[0]} not found on {searched}")
    argv[0] = resolved
    if model and cfg.get("model_flag"):
        argv += [cfg["model_flag"], model]
    full = f"{system}\n\n{prompt}" if system else prompt
    argv.append(full)
    env = os.environ.copy()
    for k in cfg.get("unset_env", []):
        env.pop(k, None)
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=max(timeout, CLI_TIMEOUT), env=env,
                              stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as e:
        raise CliError(f"{provider} timed out after {max(timeout, CLI_TIMEOUT)}s") from e
    except FileNotFoundError as e:
        raise CliError(f"{provider} not installed: {argv[0]}") from e
    out = (proc.stdout or "").strip()
    if proc.returncode != 0:
        raise CliError(f"{provider} exit {proc.returncode}: {(proc.stderr or out)[:160]}")
    low = out.lower()
    if not out or any(t in low for t in _CLI_FAIL_TEXT):
        raise CliError(f"{provider} provider-limit/empty: {out[:120]!r}")
    return out


class RouteExhausted(RuntimeError):
    """Every provider in the role's chain failed. Carries the per-attempt log."""

    def __init__(self, role: str, attempts: list["Attempt"]):
        self.role = role
        self.attempts = attempts
        trail = " | ".join(f"{a.provider}/{a.model}: {a.error}" for a in attempts)
        super().__init__(f"route({role!r}) exhausted all {len(attempts)} providers: {trail}")


@dataclass
class Attempt:
    provider: str
    model: str
    ok: bool = False
    error: str = ""


@dataclass
class RouteResult:
    role: str
    provider: str
    model: str
    text: str
    attempts: list[Attempt] = field(default_factory=list)


def _forced_fail() -> set[str]:
    raw = os.environ.get("HERMES_ROUTE_FAIL", "")
    return {p.strip() for p in raw.split(",") if p.strip()}


# Some providers (notably Anthropic) report dead credits / quota as a 400, not 402/429.
# Those MUST fail over; a genuinely malformed-request 400 must not.
_BILLING_400 = ("credit", "billing", "balance", "quota", "payment", "insufficient", "top up", "top-up")


def _should_rotate(err: Exception) -> bool:
    if isinstance(err, BadRequestError):
        msg = str(getattr(err, "message", None) or err).lower()
        if any(k in msg for k in _BILLING_400):  # billing/quota miscoded as 400 → rotate
            return True
        return False  # real malformed request — rotating providers won't help
    if isinstance(err, ROTATE_ON):
        return True
    if isinstance(err, APIStatusError):
        # 401/402/403 (auth/billing) and any other server status → fail over.
        return True
    # Unknown/transport error → be resilient, rotate.
    return True


def route(role: str, prompt: str, *, timeout: float = DEFAULT_TIMEOUT,
          system: str | None = None, max_tokens: int | None = None) -> RouteResult:
    """Send `prompt` to the first provider in `role`'s chain that succeeds.

    Rotates on 429/503/timeout/conn/auth-billing; raises BadRequestError on a 400
    and RouteExhausted if the whole chain fails.
    """
    if role not in ROLE_CHAINS:
        raise KeyError(f"unknown role {role!r}; known: {sorted(ROLE_CHAINS)}")

    forced = _forced_fail()
    attempts: list[Attempt] = []
    messages = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]

    for provider, model in ROLE_CHAINS[role]:
        att = Attempt(provider=provider, model=model)
        try:
            cfg = PROVIDERS[provider]
            if provider in forced:
                raise RateLimitError(  # simulated 429 for the fallback proof
                    message=f"HERMES_ROUTE_FAIL forced 429 for {provider}",
                    response=httpx.Response(429, request=httpx.Request("POST", "https://forced.test")),
                    body=None,
                )
            if cfg.get("transport") == "cli":
                text = _call_cli(provider, cfg, model, prompt, system, timeout)
            else:
                key = os.environ.get(cfg["key_env"], "")
                if not key:  # treat a missing key as a provider outage → rotate
                    raise APIConnectionError(message=f"no {cfg['key_env']}",
                                             request=httpx.Request("POST", cfg["base_url"]))
                client = OpenAI(base_url=cfg["base_url"], api_key=key, timeout=timeout, max_retries=0)
                kw: dict = {"model": model, "messages": messages}
                if max_tokens is not None:
                    kw["max_tokens"] = max_tokens
                resp = client.chat.completions.create(**kw)
                text = resp.choices[0].message.content or ""
            att.ok = True
            attempts.append(att)
            return RouteResult(role=role, provider=provider, model=model, text=text, attempts=attempts)
        except Exception as err:  # noqa: BLE001 - resilience boundary
            att.error = f"{type(err).__name__}: {str(err)[:160]}"
            attempts.append(att)
            if not _should_rotate(err):  # genuine malformed-request 400 → propagate
                raise
            continue

    raise RouteExhausted(role, attempts)


def _cli() -> int:
    if len(sys.argv) < 3:
        sys.stderr.write("usage: route.py <coordinator|strategist|executor> <prompt>\n")
        return 2
    role, prompt = sys.argv[1], sys.argv[2]
    t0 = time.monotonic()
    res = route(role, prompt)
    dt = time.monotonic() - t0
    trail = " -> ".join(f"{a.provider}({'ok' if a.ok else 'fail'})" for a in res.attempts)
    sys.stderr.write(f"[route] {role}: {trail} via {res.provider}/{res.model} in {dt:.1f}s\n")
    print(res.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
