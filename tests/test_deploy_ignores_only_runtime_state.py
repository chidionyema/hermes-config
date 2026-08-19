"""The deploy gate may ignore state the agent writes. It may never ignore code.

`deploy/hermes/deploy.sh` refuses a dirty tree, which is what stops a session's
half-finished branch reaching production. But this repo also tracks files the
running agent rewrites, so the tree goes dirty within seconds of a deploy and the
gate refuses work nobody left uncommitted. Measured 2026-08-19, two deploys in a
row: `channel_directory.json` (now untracked), then `policies/*.json` counters and
a re-encrypted `secrets.age`.

The escape hatch for that is `deploy/hermes/runtime-written.txt`, and an escape
hatch with no fence around it becomes the way every awkward change gets shipped.
These tests are the fence: every entry carries a reason, no entry may be source,
and the filter must still catch a real edit.
"""

import re
import subprocess
from pathlib import Path

HERMES = Path.home() / ".hermes"
DEPLOY = HERMES / "deploy/hermes/deploy.sh"
LIST = HERMES / "deploy/hermes/runtime-written.txt"

CODE_SUFFIXES = (".py", ".sh", ".ts", ".js", ".tsx", ".jsx")
CODE_DIRS = ("scripts/", "hermes-agent/", "tests/", "deploy/")


def _entries() -> list[str]:
    return [ln.strip() for ln in LIST.read_text().splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


def test_the_list_is_not_empty():
    """A guard that iterates an empty list passes."""
    assert _entries(), "runtime-written.txt declares nothing, so nothing is being tested"


def test_no_entry_is_source_code():
    for entry in _entries():
        assert not entry.endswith(CODE_SUFFIXES), f"{entry} is source"
        assert not entry.startswith(CODE_DIRS), f"{entry} is a source directory"


def test_every_entry_has_a_reason_above_it():
    """A path with no reason is a path nobody can review later."""
    lines = LIST.read_text().splitlines()
    for i, raw in enumerate(lines):
        entry = raw.strip()
        if not entry or entry.startswith("#"):
            continue
        preceding = [ln.strip() for ln in lines[:i] if ln.strip()]
        assert preceding and preceding[-1].startswith("#"), (
            f"{entry} has no comment immediately above it saying why it is ignored"
        )


def test_the_gate_refuses_a_code_entry_rather_than_honouring_it():
    """Adding a .py file to the list must fail the deploy, not silence it."""
    body = DEPLOY.read_text()
    assert "runtime-written.txt lists" in body, "the refusal branch is gone"
    assert re.search(r"\*\.py\|.*\*\.sh", body), "the code-suffix check is gone"


def test_the_filter_still_catches_a_real_edit():
    """Run the gate's own filter over a synthetic status listing.

    The failure this refuses: a pattern loose enough to swallow everything, which
    would turn the dirty check into a no-op while still looking installed.
    """
    script = r'''
      ignore_re='^\.\. vendor/'
      while IFS= read -r entry; do
        case "$entry" in ''|'#'*) continue ;; esac
        ignore_re="$ignore_re|^.. $(printf '%s' "$entry" | sed 's/[.[\*^$]/\\&/g')"
      done < "$1"
      printf '%s\n' " M policies/pol-auto-fix-cron.json" " M secrets.age" \
                    " M scripts/coordinator.py" " M config.yaml" \
        | grep -Ev "$ignore_re" || true
    '''
    out = subprocess.run(["bash", "-c", script, "_", str(LIST)],
                         capture_output=True, text=True, timeout=30).stdout
    assert "scripts/coordinator.py" in out, "a code change was filtered out"
    assert "config.yaml" in out, "a config change was filtered out"
    assert "policies/" not in out, "the declared runtime path was not filtered"
    assert "secrets.age" not in out, "the declared runtime path was not filtered"
