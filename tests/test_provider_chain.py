"""The chain that relabelled every failure as a Gemini 429 must fail this test.

See scripts/provider_chain_check.py for the incident. These cases are the config that was live
on 2026-08-19 and the config that replaced it, so the test proves the fix rather than the code.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".hermes" / "scripts"))

from provider_chain_check import chain_from_config, check_chain  # noqa: E402

# The environment on prospector-hermes: MiniMax has a key, nothing else does.
CONTAINER_ENV = {"MINIMAX_API_KEY": "sk-live", "GEMINI_API_KEY": "", "ANTHROPIC_API_KEY": ""}

BROKEN_CONFIG = {  # config.yaml as it stood at 2026-08-19T19:58, when the summary job died
    "model": {"provider": "minimax", "default": "MiniMax-M3"},
    "fallback_model": [
        {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
        {"provider": "gemini", "model": "gemini-2.5-flash"},
    ],
}
FIXED_CONFIG = {"model": {"provider": "minimax", "default": "MiniMax-M3"}, "fallback_model": []}


def _verdicts(cfg):
    return {r["provider"]: r["verdict"] for r in check_chain(chain_from_config(cfg), CONTAINER_ENV)}


def test_the_dead_chain_is_refused():
    v = _verdicts(BROKEN_CONFIG)
    assert v["minimax"] == "OK"
    assert v["anthropic"] == "NO_CREDENTIAL"
    assert v["gemini"] == "NO_CREDENTIAL"


def test_the_fixed_chain_passes():
    assert _verdicts(FIXED_CONFIG) == {"minimax": "OK"}


def test_the_live_config_has_no_dead_links():
    """The real check. If someone re-adds a keyless provider, this is what says so."""
    import yaml

    cfg = yaml.safe_load((Path.home() / ".hermes" / "config.yaml").read_text()) or {}
    bad = [r for r in check_chain(chain_from_config(cfg)) if r["verdict"] != "OK"]
    assert not bad, [f"{r['provider']}: {r['detail']}" for r in bad]


def test_fallback_providers_wins_over_fallback_model():
    """Grade the list the cron scheduler actually walks, not the one that reads nicer."""
    cfg = {
        "model": {"provider": "minimax"},
        "fallback_providers": [{"provider": "deepseek"}],
        "fallback_model": [{"provider": "gemini"}],
    }
    assert [c["provider"] for c in chain_from_config(cfg)] == ["minimax", "deepseek"]


def test_a_bare_string_entry_is_still_checked():
    cfg = {"model": {"provider": "minimax"}, "fallback_model": ["anthropic"]}
    assert _verdicts(cfg)["anthropic"] == "NO_CREDENTIAL"


def test_an_unknown_provider_is_reported_not_waved_through():
    cfg = {"model": {"provider": "minimax"}, "fallback_model": [{"provider": "nonesuch"}]}
    assert _verdicts(cfg)["nonesuch"] == "UNKNOWN"
