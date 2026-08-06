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
import json
import os
import shutil
import tempfile
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

_unregistered = all_providers - set(R.PROVIDERS)
check("every chain provider is registered", not _unregistered, f"unknown={_unregistered}")
if _unregistered:
    # HARD STOP. Every later check indexes PROVIDERS[provider], so an unregistered
    # name in a chain used to end this suite in a KeyError traceback — exit 1 with
    # no verdict line, which reads like a broken test rather than a broken chain.
    # The diagnosis has to survive to the report. (Found by neutering, 2026-08-06:
    # a probe that put retired `gemini` back in executor produced exit=1 and zero
    # ❌ lines.)
    print(f"\n❌ FAIL  chain names a provider that is not in PROVIDERS: {sorted(_unregistered)}")
    print("   Every downstream check indexes PROVIDERS[...] — stopping here rather "
          "than dying in a traceback.")
    sys.exit(1)

check("coordinator primary is claude-cli (subscription, founder direction 2026-08-06)",
      R.ROLE_CHAINS["coordinator"][0] == ("claude-cli", ""),
      str(R.ROLE_CHAINS["coordinator"][0]))

# Retired providers must leave the REGISTRY, not just the chains. Founder call
# 2026-08-06 on both. Demotion is not removal: anything that can still be named
# in routing.json can still be routed to.
for _dead in ("agy-cli", "gemini"):
    check(f"{_dead} is retired from the registry, not merely unused",
          _dead not in R.PROVIDERS, f"still registered: {R.PROVIDERS.get(_dead)}")

check("executor primary is minimax", R.ROLE_CHAINS["executor"][0][0] == "minimax",
      str(R.ROLE_CHAINS["executor"][0]))

check("strategist primary is claude-cli (subscription)",
      R.ROLE_CHAINS["strategist"][0] == ("claude-cli", ""), str(R.ROLE_CHAINS["strategist"][0]))
# The property that matters is INDEPENDENCE of transport, not a count. The old
# assertion pinned the literal list ["claude-cli","agy-cli","deepseek"], so it
# failed the moment two of those three were measured dead (2026-08-06: deepseek
# balance -0.22/is_available false; agy quota-blocked 156h, now retired) and the chain was
# corrected. Pin the invariant instead, so a future re-point does not need a
# test edit — only a genuinely worse chain does.
_strat = R.ROLE_CHAINS["strategist"]
check("strategist primary is a CLI (subscription, not pay-per-token)",
      R.PROVIDERS[_strat[0][0]]["transport"] == "cli", str(_strat[0]))
check("strategist has a fallback on a DIFFERENT transport",
      len({R.PROVIDERS[p]["transport"] for p, _m in _strat}) > 1, str(_strat))

# No chain may CONTAIN a provider we have measured as unable to serve — not just
# at the head. The head rule alone is what let gemini sit in executor's only
# fallback seat while its completions 429'd on depleted credits: the chain looked
# two-deep and was one-deep. All three of these authenticate fine and cannot
# serve, which is why a /models probe never caught any of them.
_KNOWN_DEAD = {
    "deepseek",   # /user/balance -> is_available false, total_balance "-0.22"
    "anthropic",  # dead credits (400 "credit balance is too low")
    # Retired from PROVIDERS entirely, so the loop below normally never sees
    # them. They stay named here as a TRIPWIRE: re-registering one (a revert, a
    # merge, a "let's try it again") must not also silently re-permit it in a
    # chain. Dropping them from this set is what made this very check vacuous
    # when it was first written — proven by neutering, 2026-08-06.
    "gemini",     # 429 "Your prepayment credits are depleted"
    "agy-cli",    # "Individual quota reached ... Resets in 155h51m58s"
}
for _role, _chain in R.ROLE_CHAINS.items():
    _dead_in_chain = [p for p, _m in _chain if p in _KNOWN_DEAD]
    check(f"{_role} chain contains no known-dead provider",
          not _dead_in_chain, f"dead legs={_dead_in_chain} chain={_chain}")
    check(f"{_role} has a real second leg",
          len(_chain) >= 2, str(_chain))
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
_exec_chain = R.ROLE_CHAINS["executor"]
os.environ["HERMES_ROUTE_FAIL"] = ",".join(p for p, _m in _exec_chain)
try:
    R.route("executor", "ping")
    check("exhausted chain raises RouteExhausted", False, "no exception raised")
except R.RouteExhausted as e:
    check("exhausted chain raises RouteExhausted",
          len(e.attempts) == len(_exec_chain), f"attempts={len(e.attempts)} chain={len(_exec_chain)}")
except Exception as e:  # noqa: BLE001
    check("exhausted chain raises RouteExhausted", False, f"wrong type {type(e).__name__}")
finally:
    os.environ.pop("HERMES_ROUTE_FAIL", None)


# ── LIVE fallback proof — the headline ─────────────────────────────────────────
# Force executor's primary (minimax) down; assert a REAL completion from the
# LAST leg of the chain. These probes derive the providers from ROLE_CHAINS
# rather than naming them, so re-pointing a chain (which the founder said WILL
# happen as prices move) does not silently turn the live proof into a no-op
# against a provider that is no longer in the chain at all.
_ex_primary, _ = R.ROLE_CHAINS["executor"][0]
_ex_backup, _ex_backup_model = R.ROLE_CHAINS["executor"][-1]
_ex_label = f"LIVE: executor falls {_ex_primary} -> {_ex_backup}"


def _usable(provider: str) -> str:
    """'' if the provider can be probed live, else the reason to skip.

    Gating on key_env alone silently SKIPPED any chain whose fallback is a CLI
    (no key_env -> os.environ.get("") -> None), which would have turned the live
    proof into a no-op the moment a chain re-pointed at claude-cli.
    """
    cfg = R.PROVIDERS[provider]
    if cfg["transport"] == "cli":
        return "" if R._resolve_cli_binary(cfg["argv"][0]) else f"{cfg['argv'][0]} not on PATH"
    key = cfg.get("key_env", "")
    return "" if os.environ.get(key) else f"{key} unset"


if not _usable(_ex_backup):
    os.environ["HERMES_ROUTE_FAIL"] = _ex_primary
    try:
        # NB: reasoner models spend budget on a reasoning pass before content —
        # give output room, else content comes back empty (finish=length).
        res = R.route("executor", "Reply with exactly the word: ALIVE", max_tokens=256)
        primary_failed = res.attempts[0].provider == _ex_primary and not res.attempts[0].ok
        check(f"LIVE: primary {_ex_primary} killed mid-task", primary_failed,
              f"attempt0={res.attempts[0].provider}/{res.attempts[0].ok}")
        check(_ex_label, res.provider == _ex_backup and bool(res.text.strip()),
              f"served_by={res.provider}/{res.model} text={res.text.strip()[:40]!r}")
    except Exception as e:  # noqa: BLE001
        check(_ex_label, False, f"{type(e).__name__}: {str(e)[:120]}")
    finally:
        os.environ.pop("HERMES_ROUTE_FAIL", None)
else:
    skip(_ex_label, _usable(_ex_backup))

# ── LIVE: the CLI strategist rotates into its HTTP fallback ────────────────────
# This is the case the estate actually hits: the Claude Code subscription is
# rate-limited or the binary is invisible to launchd, and work must still land.
_st_primary, _ = R.ROLE_CHAINS["strategist"][0]
_st_backup, _st_backup_model = R.ROLE_CHAINS["strategist"][-1]
_st_label = f"LIVE: strategist falls {_st_primary} -> {_st_backup}"
if not _usable(_st_backup):
    os.environ["HERMES_ROUTE_FAIL"] = _st_primary
    try:
        res = R.route("strategist", "Reply with exactly the word: ALIVE", max_tokens=256)
        check(_st_label,
              res.provider == _st_backup and res.model == _st_backup_model and bool(res.text.strip()),
              f"served_by={res.provider}/{res.model}")
    except Exception as e:  # noqa: BLE001
        check(_st_label, False, f"{type(e).__name__}: {str(e)[:120]}")
    finally:
        os.environ.pop("HERMES_ROUTE_FAIL", None)
else:
    skip(_st_label, _usable(_st_backup))

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


# ── The launchd PATH trap ──────────────────────────────────────────────────────
# THE production bug: launchd starts the daemon with PATH=/usr/bin:/bin:/usr/sbin:/sbin,
# which does not contain ~/.local/bin. shutil.which("claude") returned None there, so
# claude-cli raised "not installed" on every call and the estate concluded the
# subscription brain was gone. It was on disk the whole time. This test runs the
# lookup under that exact PATH.
_LAUNCHD_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
_real_path = os.environ.get("PATH", "")
try:
    os.environ["PATH"] = _LAUNCHD_PATH
    _bare = shutil.which("claude")
    _resolved = R._resolve_cli_binary("claude")
    # Non-vacuity is asserted in the test itself: if the bare lookup ALSO finds it,
    # this machine cannot reproduce the trap and the test proves nothing — say so.
    check("launchd's bare PATH really does hide the claude binary", _bare is None,
          f"shutil.which found {_bare} on {_LAUNCHD_PATH} — trap not reproducible here")
    check("_resolve_cli_binary finds claude despite launchd's bare PATH",
          _resolved is not None and os.path.isabs(_resolved) and os.access(_resolved, os.X_OK),
          f"resolved={_resolved}")
    check("_resolve_cli_binary still returns None for a genuinely missing binary",
          R._resolve_cli_binary("hermes-no-such-binary-xyz") is None)
finally:
    os.environ["PATH"] = _real_path


# ── Operator override (routing.json) ───────────────────────────────────────────
# Founder direction 2026-08-06: the provider order tracks model price and
# capability and WILL change. Re-pointing it must not require a code edit — but
# an override that accepts anything is worse than none, because a typo would
# silently leave a role routed at a provider that does not exist.
_ORIG_CHAINS = {k: list(v) for k, v in R.ROLE_CHAINS.items()}


def _with_override(payload, *, raw=None):
    """Write an override file, apply it, return (changed_roles, resulting_chains)."""
    d = tempfile.mkdtemp()
    f = os.path.join(d, "routing.json")
    with open(f, "w") as fh:
        fh.write(raw if raw is not None else json.dumps(payload))
    try:
        changed = R._apply_routing_override(f)
        return changed, {k: list(v) for k, v in R.ROLE_CHAINS.items()}
    finally:
        R.ROLE_CHAINS.clear()
        R.ROLE_CHAINS.update({k: list(v) for k, v in _ORIG_CHAINS.items()})
        shutil.rmtree(d, ignore_errors=True)


_changed, _after = _with_override({"executor": [["claude-cli", ""], ["minimax", "MiniMax-M3"]]})
check("override re-points a role with no code edit",
      _changed == ["executor"] and _after["executor"] == [("claude-cli", ""), ("minimax", "MiniMax-M3")],
      f"changed={_changed} executor={_after.get('executor')}")
check("override leaves untargeted roles alone",
      _after["coordinator"] == _ORIG_CHAINS["coordinator"], str(_after.get("coordinator")))

_changed, _after = _with_override({"exeuctor": [["minimax", "MiniMax-M3"]]})  # typo'd role
check("override rejects an unknown ROLE instead of inventing one",
      _changed == [] and _after == _ORIG_CHAINS, f"changed={_changed}")

_changed, _after = _with_override({"executor": [["deepsek", "x"]]})  # typo'd provider
check("override rejects an unregistered PROVIDER (a typo must not route to nothing)",
      _changed == [] and _after == _ORIG_CHAINS, f"changed={_changed}")

_changed, _after = _with_override({"executor": []})
check("override rejects an EMPTY chain (a role with no providers can never serve)",
      _changed == [] and _after == _ORIG_CHAINS, f"changed={_changed}")

_changed, _after = _with_override(None, raw="{not json at all")
check("malformed override warns and keeps the compiled-in chains",
      _changed == [] and _after == _ORIG_CHAINS, f"changed={_changed}")

check("a missing override file is a silent no-op, not an error",
      R._apply_routing_override(os.path.join(tempfile.mkdtemp(), "absent.json")) == [])
check("chains survived every override test unchanged",
      {k: list(v) for k, v in R.ROLE_CHAINS.items()} == _ORIG_CHAINS, str(R.ROLE_CHAINS))


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
