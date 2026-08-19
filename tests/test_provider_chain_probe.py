"""A present key is not a live brain — the probe must say so.

Measured 2026-08-19 on prospector-hermes. `provider_chain_check.py` (credential mode) printed

    ✅ primary  minimax  MiniMax-M3  credential in MINIMAX_API_KEY
    provider-chain OK: every configured provider can authenticate here.

at the same moment a direct call to that provider, from inside the deployed machine, returned

    HTTP 429: Token Plan usage limit reached: Upgrade your Token Plan or purchase Credits (2056)

Prospector already wrote this class down as `models-probe-proves-the-key-not-the-balance`. These
cases pin the classification so hermes cannot rediscover it a third time.

The two that matter most:
  - a 429 whose body names credit is NO_CREDIT, and NO_CREDIT is never counted live
  - a transport failure is UNREACHABLE, never NO_CREDIT: a dropped wifi link must not send the
    founder to a billing page
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

HERMES = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
sys.path.insert(0, str(HERMES / "scripts"))

from provider_chain_check import (  # noqa: E402
    _classify,
    _first_line,
    _provider_base_url,
    _probe_request,
    probe_chain,
)


@pytest.mark.parametrize("status,body,expected", [
    (429, '{"error":{"message":"Token Plan usage limit reached: Upgrade your Token Plan or '
          'purchase Credits for more usage. (2056)"}}', "NO_CREDIT"),
    (402, '{"error":{"message":"Insufficient Balance"}}', "NO_CREDIT"),
    (429, '{"error":{"code":429,"message":"Your prepayment credits are depleted."}}', "NO_CREDIT"),
    (429, '{"error":{"message":"Too many requests, slow down"}}', "RATE_LIMITED"),
    (401, '{"error":{"message":"invalid x-api-key"}}', "BAD_CREDENTIAL"),
    (404, '{"error":{"message":"model not found"}}', "NO_MODEL"),
])
def test_classification(status, body, expected):
    assert _classify(status, body)[0] == expected


def test_the_exact_response_that_read_as_healthy_is_not_live():
    """The literal MiniMax body from 2026-08-19 must never grade as a working brain."""
    verdict, detail = _classify(
        429,
        '{"type":"error","error":{"type":"rate_limit_error","message":"Token Plan usage limit '
        'reached: Upgrade your Token Plan or purchase Credits for more usage. (2056)"}}',
    )
    assert verdict == "NO_CREDIT"
    assert verdict != "LIVE"
    assert "Token Plan usage limit reached" in detail


def test_transport_failure_is_never_a_billing_problem(monkeypatch):
    import urllib.request

    def boom(*a, **k):
        raise OSError("Network is unreachable")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    out = probe_chain([{"provider": "minimax", "model": "MiniMax-M3", "role": "primary"}],
                      {}, env={"MINIMAX_API_KEY": "x"})
    assert out[0]["verdict"] == "UNREACHABLE"
    assert out[0]["verdict"] != "NO_CREDIT"


def test_missing_credential_is_reported_not_probed(monkeypatch):
    import urllib.request

    def boom(*a, **k):
        raise AssertionError("must not spend a call with no credential")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    out = probe_chain([{"provider": "minimax", "model": "MiniMax-M3", "role": "primary"}],
                      {}, env={})
    assert out[0]["verdict"] == "NO_CREDENTIAL"


def test_unknown_provider_is_not_assumed_fine():
    out = probe_chain([{"provider": "not-a-real-vendor", "model": "x", "role": "fallback"}],
                      {}, env={})
    assert out[0]["verdict"] in ("NO_PROBE", "NO_CREDENTIAL")
    assert out[0]["verdict"] != "LIVE"


def test_primary_base_url_comes_from_the_model_block():
    cfg = {"model": {"provider": "minimax", "base_url": "https://api.minimax.io/anthropic/"},
           "providers": {"minimax": {"base_url": "https://wrong.example"}}}
    assert _provider_base_url(cfg, "minimax", "primary") == "https://api.minimax.io/anthropic"
    assert _provider_base_url(cfg, "minimax", "fallback") == "https://wrong.example"


def test_minimax_probe_uses_the_anthropic_wire_format():
    url, headers, body = _probe_request("minimax", "MiniMax-M3", "k",
                                        "https://api.minimax.io/anthropic")
    assert url.endswith("/v1/messages")
    assert headers["Authorization"] == "Bearer k"
    assert body["max_tokens"] <= 16, "a liveness probe must not buy a real answer"


def test_first_line_extracts_the_vendor_message_not_the_envelope():
    assert _first_line('{"error":{"message":"Insufficient Balance"}}') == "Insufficient Balance"
    assert _first_line("not json at all") == "not json at all"
