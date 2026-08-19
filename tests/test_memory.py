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


def test_user_md_carries_the_audit_rule_in_whatever_words_it_currently_uses():
    """The RULE must survive a rewrite of USER.md. The exact phrase must not have to.

    This test pinned the literal string "continuous audit" and went red the day the rule was
    reworded to "trust operates on a receipts ledger". The rule was intact; only the wording
    moved. USER.md itself says tests should assert behaviour invariants and not frozen strings,
    so the test was breaking the rule written directly above the line it was reading.

    A red test nobody can act on is worse than no test: it is the noise a real regression hides
    in. So this accepts any of the ways the estate has expressed the same rule, and fails only
    when none of them is there — which would mean the rule really is gone."""
    text = USER_MD.read_text()
    wordings = (r"continuous[- ]audit", r"receipts ledger", r"receipts?, not (a )?promise")
    assert any(re.search(w, text, re.I) for w in wordings), (
        "USER.md no longer carries the audit/receipts rule in any known wording. If it was "
        "deliberately reworded again, add the new wording here; if it was dropped, that is the "
        "regression this test exists to catch.")


def test_memory_retrieval_loads_user_profile():
    from conftest import load
    mr = load("memory_retrieval.py")
    profile = mr._load_user_profile()
    assert isinstance(profile, str) and "Otto" in profile
