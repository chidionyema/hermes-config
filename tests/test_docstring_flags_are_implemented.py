"""A script must implement every --flag its own docstring promises.

Measured 2026-08-19. `scripts/provider_chain_check.py` opened with a docstring that said:

    That is why the failure above ran for days -- so `--probe` spends one minimal call per
    provider when you want the stronger answer.

`--probe` was never added to its argparse. So the estate had a written, cited answer to "is the
brain alive" that nobody could run, and the weak default check went on printing

    provider-chain OK: every configured provider can authenticate here.

while every call to that provider returned HTTP 429 "Token Plan usage limit reached".

THE CLASS: a docstring is a claim about the code, and nothing graded it. A promised flag reads
exactly like a shipped flag to the next agent, who then reports that the check was run.

This test grades the claim. It scans every script with an argparse parser, pulls the `--flag`
tokens out of its module docstring, and fails when one of them is not an `add_argument`.

Proven to catch it: run this against `git show HEAD~1:scripts/provider_chain_check.py` and it
reports `--probe` missing.
"""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path

SCRIPTS = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))) / "scripts"

_FLAG = re.compile(r"(?<![\w-])--([a-zA-Z][\w-]*)")

# Flags a docstring may name without owning them. Each entry needs a reason, because an
# allowlist with no reason is how a guard is switched off one line at a time.
_NOT_OURS: dict[str, dict[str, str]] = {
    "launchd_receipt.py": {"flag": "literal placeholder in the prose 'a --flag', not a real flag"},
}


def _defined_flags(tree: ast.AST) -> tuple[bool, set[str]]:
    """(uses_argparse, every long flag passed to add_argument)."""
    uses = False
    flags = {"help"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "ArgumentParser":
            uses = True
        elif isinstance(node, ast.Name) and node.id == "ArgumentParser":
            uses = True
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and node.func.attr == "add_argument"):
            uses = True
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                        and arg.value.startswith("--"):
                    flags.add(arg.value[2:])
    return uses, flags


def test_every_documented_flag_is_implemented():
    assert SCRIPTS.is_dir(), f"{SCRIPTS} missing — the scan would silently pass on zero files"

    scanned = 0
    broken: list[str] = []
    for path in sorted(SCRIPTS.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(errors="replace"))
        except SyntaxError:
            continue
        doc = ast.get_docstring(tree) or ""
        if not doc:
            continue
        uses_argparse, defined = _defined_flags(tree)
        if not uses_argparse:
            continue
        scanned += 1
        allowed = set(_NOT_OURS.get(path.name, {}))
        missing = {m.group(1) for m in _FLAG.finditer(doc)} - defined - allowed
        for flag in sorted(missing):
            broken.append(f"{path.name}: docstring promises --{flag}, argparse never defines it")

    # A scan over nothing is a green tick that means nothing.
    assert scanned >= 20, f"only {scanned} argparse scripts scanned — the glob is wrong"
    assert not broken, "documented flags that do not exist:\n  " + "\n  ".join(broken)
