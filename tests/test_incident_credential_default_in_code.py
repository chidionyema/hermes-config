"""Incident test (rung 4): hermes-config#17, 2026-08-25.

scripts/verify_system.py shipped a real Otto API key as the os.environ.get default,
and it sat in public git history. The class: a credential read from the environment
with a non-empty literal fallback. A fallback for a credential is a default password
(AGENTS.md HARD RULE 3, LAW 46). Names that are paths or ids (HERMES_LEASE_KEY) are
outside the class; the pattern names the credential suffixes only.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATTERN = re.compile(
    r"""environ(?:\.get\(|\[)\s*["']([A-Z0-9_]*(?:API_KEY|_TOKEN|_SECRET|PASSWORD)[A-Z0-9_]*)["']\s*,\s*["']([^"']+)["']"""
)


def offenders(text: str) -> list[tuple[str, str]]:
    return [(m.group(1), m.group(2)) for m in PATTERN.finditer(text)]


def test_pattern_refuses_a_credential_default_and_permits_the_rest():
    assert offenders('TOKEN = os.environ.get("OTTO_API_KEY", "G7ULX2Hdzt8PQAlQHp1_hf1D")') == [("OTTO_API_KEY", "G7ULX2Hdzt8PQAlQHp1_hf1D")]
    assert offenders('SECRET = os.environ.get("OTTO_API_KEY", "otto_dev_key_change_in_production")')
    assert offenders('TOKEN = os.environ.get("OTTO_API_KEY", "")') == []
    assert offenders('KEY = os.environ.get("HERMES_LEASE_KEY", "hermes/leader.json")') == []


def test_no_tracked_python_file_ships_a_credential_default():
    files = subprocess.run(["git", "ls-files", "--", "*.py"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    found = []
    for f in files:
        if "/.archive/" in f or f.startswith("tests/"):
            continue
        found += [(f, name) for name, _ in offenders((ROOT / f).read_text(encoding="utf-8", errors="replace"))]
    assert found == [], f"credential defaults in code (rotate, then read from the secret store): {found}"
