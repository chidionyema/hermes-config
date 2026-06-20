#!/usr/bin/env python3
"""Proof for route.py — Phase 1 of the heavenly-estate design.

Design PROOF (line 126): "kill the primary provider mid-task; task still completes
via fallback." We drive the primary down with the HERMES_ROUTE_FAIL seam and assert
a REAL completion arrives from the live fallback provider (DeepSeek V4).

Static invariants run offline (no network). LIVE invariants make one real call each
to the configured fallback; they SKIP (not fail) if no provider key is present.

Run:  python3 ~/.hermes/scripts/test_route.py
Exit: 0 = all green, 1 = a hard invariant failed.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import route as R  # noqa: E402
from openai import BadRequestError, RateLimitError  # noqa: E402

import httpx  # noqa: E402

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
results: list[tuple[str, str, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((PASS if cond else FAIL, name, detail))


def skip(name: str, detail: str) -> None:
    results.append((SKIP, name, detail))


# ── Static invariants (offline) ────────────────────────────────────────────────
check("3 roles defined", set(R.ROLE_CHAINS) == {"coordinator", "strategist", "executor"},
      str(sorted(R.ROLE_CHAINS)))

all_providers = {p for chain in R.ROLE_CHAINS.values() for (p, _m) in chain}
check("no openrouter anywhere", "openrouter" not in all_providers and
      all("openrouter" not in v.get("base_url", "") for v in R.PROVIDERS.values()),
      str(sorted(all_providers)))

check("every chain provider is registered", all_providers <= set(R.PROVIDERS),
      f"unknown={all_providers - set(R.PROVIDERS)}")

check("coordinator primary is deepseek v4",
      R.ROLE_CHAINS["coordinator"][0] == ("deepseek", "deepseek-v4-flash"),
      str(R.ROLE_CHAINS["coordinator"][0]))

check("executor primary is minimax", R.ROLE_CHAINS["executor"][0][0] == "minimax",
      str(R.ROLE_CHAINS["executor"][0]))

check("strategist primary is claude-cli (subscription)",
      R.ROLE_CHAINS["strategist"][0] == ("claude-cli", ""), str(R.ROLE_CHAINS["strategist"][0]))
check("strategist has 3 independent backends (cli,cli,http)",
      [p for p, _m in R.ROLE_CHAINS["strategist"]] == ["claude-cli", "agy-cli", "deepseek"],
      str(R.ROLE_CHAINS["strategist"]))
check("claude-cli unsets the dead ANTHROPIC_API_KEY (forces subscription)",
      "ANTHROPIC_API_KEY" in R.PROVIDERS["claude-cli"].get("unset_env", []))

# rotation policy: 429 rotates, 400 does not
_req = httpx.Request("POST", "https://example.test")
check("rotates on 429 (RateLimitError)",
      R._should_rotate(RateLimitError(message="x", response=httpx.Response(429, request=_req), body=None)))
check("does NOT rotate on a malformed-request 400",
      not R._should_rotate(BadRequestError(message="invalid 'messages' field", response=httpx.Response(400, request=_req), body=None)))
check("DOES rotate on a billing 400 (Anthropic dead-credits)",
      R._should_rotate(BadRequestError(message="Your credit balance is too low to access the Anthropic API",
                                       response=httpx.Response(400, request=_req), body=None)))

# whole-chain failure raises RouteExhausted (forced, offline)
os.environ["HERMES_ROUTE_FAIL"] = "minimax,deepseek,gemini"
try:
    R.route("executor", "ping")
    check("exhausted chain raises RouteExhausted", False, "no exception raised")
except R.RouteExhausted as e:
    check("exhausted chain raises RouteExhausted", len(e.attempts) == 3, f"attempts={len(e.attempts)}")
except Exception as e:  # noqa: BLE001
    check("exhausted chain raises RouteExhausted", False, f"wrong type {type(e).__name__}")
finally:
    os.environ.pop("HERMES_ROUTE_FAIL", None)


# ── LIVE fallback proof — the headline ─────────────────────────────────────────
# Force executor's primary (minimax) down; assert a REAL completion from deepseek.
if os.environ.get("DEEPSEEK_API_KEY"):
    os.environ["HERMES_ROUTE_FAIL"] = "minimax"
    try:
        # NB: deepseek-v4 models are reasoners — give output budget room for the
        # reasoning_content pass, else content comes back empty (finish=length).
        res = R.route("executor", "Reply with exactly the word: ALIVE", max_tokens=256)
        primary_failed = res.attempts[0].provider == "minimax" and not res.attempts[0].ok
        served_by_fallback = res.provider == "deepseek"
        got_text = bool(res.text.strip())
        check("LIVE: primary minimax killed mid-task", primary_failed,
              f"attempt0={res.attempts[0].provider}/{res.attempts[0].ok}")
        check("LIVE: completed via deepseek-v4 fallback", served_by_fallback and got_text,
              f"served_by={res.provider}/{res.model} text={res.text.strip()[:40]!r}")
    except Exception as e:  # noqa: BLE001
        check("LIVE: completed via deepseek-v4 fallback", False, f"{type(e).__name__}: {str(e)[:120]}")
    finally:
        os.environ.pop("HERMES_ROUTE_FAIL", None)
else:
    skip("LIVE: completed via deepseek-v4 fallback", "DEEPSEEK_API_KEY unset")

# ── LIVE: CLI strategist backends rotate into the HTTP fallback ─────────────────
# Force BOTH CLI strategists down; assert the chain falls over to deepseek-v4-pro.
if os.environ.get("DEEPSEEK_API_KEY"):
    os.environ["HERMES_ROUTE_FAIL"] = "claude-cli,agy-cli"
    try:
        res = R.route("strategist", "Reply with exactly the word: ALIVE", max_tokens=256)
        check("LIVE: strategist CLI→CLI→deepseek-v4-pro rotation",
              res.provider == "deepseek" and res.model == "deepseek-v4-pro" and bool(res.text.strip()),
              f"served_by={res.provider}/{res.model}")
    except Exception as e:  # noqa: BLE001
        check("LIVE: strategist CLI→CLI→deepseek-v4-pro rotation", False, f"{type(e).__name__}: {str(e)[:120]}")
    finally:
        os.environ.pop("HERMES_ROUTE_FAIL", None)
else:
    skip("LIVE: strategist CLI→CLI→deepseek-v4-pro rotation", "DEEPSEEK_API_KEY unset")

# ── LIVE: claude-cli transport actually works on the subscription ───────────────
import shutil  # noqa: E402
if shutil.which("claude"):
    try:
        res = R.route("strategist", "Reply with exactly the word: ALIVE")
        check("LIVE: claude-cli strategist serves on subscription",
              res.provider == "claude-cli" and "ALIVE" in res.text.upper(),
              f"served_by={res.provider} text={res.text.strip()[:40]!r}")
    except Exception as e:  # noqa: BLE001
        check("LIVE: claude-cli strategist serves on subscription", False, f"{type(e).__name__}: {str(e)[:120]}")
else:
    skip("LIVE: claude-cli strategist serves on subscription", "claude CLI not installed")


# ── Report ─────────────────────────────────────────────────────────────────────
print()
for status, name, detail in results:
    mark = {PASS: "✅", FAIL: "❌", SKIP: "⏭ "}[status]
    line = f"{mark} {status}  {name}"
    if detail and status != PASS:
        line += f"  — {detail}"
    print(line)

hard_fail = sum(1 for s, _n, _d in results if s == FAIL)
passed = sum(1 for s, _n, _d in results if s == PASS)
skipped = sum(1 for s, _n, _d in results if s == SKIP)
print(f"\n{passed} passed, {hard_fail} failed, {skipped} skipped")
sys.exit(1 if hard_fail else 0)
