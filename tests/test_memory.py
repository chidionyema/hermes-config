"""memory — USER.md must load within the configured char limit (Item 10 invariant).

The continuous-audit rule could not be added because USER.md was at its char limit.
This test is the standing receipt that the limit was raised and the consolidated
profile (including the continuous-audit rule) fits and loads.
"""
import re
from pathlib import Path

HERMES = Path(__file__).resolve().parent.parent
USER_MD = HERMES / "memories" / "USER.md"
CONFIG = HERMES / "config.yaml"


def _user_char_limit() -> int:
    m = re.search(r"^\s*user_char_limit:\s*(\d+)", CONFIG.read_text(), re.M)
    assert m, "user_char_limit not found in config.yaml"
    return int(m.group(1))


def test_user_md_fits_under_limit():
    text = USER_MD.read_text()
    assert len(text) <= _user_char_limit(), (
        f"USER.md is {len(text)} chars but limit is {_user_char_limit()}")


def test_user_md_carries_continuous_audit_rule():
    assert re.search(r"continuous[- ]audit", USER_MD.read_text(), re.I)


def test_memory_retrieval_loads_user_profile():
    from conftest import load
    mr = load("memory_retrieval.py")
    profile = mr._load_user_profile()
    assert isinstance(profile, str) and "Otto" in profile
