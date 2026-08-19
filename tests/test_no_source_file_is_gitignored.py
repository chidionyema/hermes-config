"""A source file that git ignores is a file that does not exist anywhere but this laptop.

The failure is quiet, and it accuses the wrong thing. `git add` prints a hint rather than an
error, the commit succeeds without the file, the push succeeds, and CI fails somewhere else
entirely — on 2026-08-19 it failed inside a workflow step whose own YAML was correct.

The cause was `*key*` in .gitignore, a rule written to keep secrets out that also matched
scripts/ci_mint_agent_deploy_key.sh. Broad secret rules are right. They just need to stop at
extensions no key ever has.
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Directories whose contents are code the repository must carry, never runtime state.
SOURCE_DIRS = ("scripts", ".github", "deploy", "recovery")
SOURCE_SUFFIXES = (".py", ".sh", ".yml", ".yaml", ".toml", ".conf")
# Real build and cache output, which is ignored on purpose.
EXCLUDED_PARTS = {"__pycache__", ".pytest_cache", "node_modules", ".venv", "venv", ".git"}


def _candidates():
    for d in SOURCE_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
                continue
            if EXCLUDED_PARTS & set(path.relative_to(ROOT).parts):
                continue
            yield path.relative_to(ROOT)


def test_no_source_file_is_gitignored():
    paths = sorted(str(p) for p in _candidates())
    assert paths, "found no source files to check — the walk itself is broken"
    # One call, not one per file: check-ignore reads every path from stdin.
    #
    # NO --verbose HERE, and that is the whole correctness of this test. With --verbose git
    # prints the last pattern that MATCHED, which includes a negation like `!*key*.sh` — a
    # line that means the file is NOT ignored. The first draft of this test read those lines
    # as failures and went red on the very file the negation had just rescued. Plain
    # check-ignore prints only paths that are actually excluded.
    proc = subprocess.run(
        ["git", "check-ignore", "--stdin"],
        cwd=ROOT, input="\n".join(paths), capture_output=True, text=True,
    )
    # Exit 0 means at least one path is ignored, 1 means none is, anything else is an error.
    assert proc.returncode in (0, 1), f"git check-ignore failed: {proc.stderr}"
    ignored = [line for line in proc.stdout.splitlines() if line.strip()]
    if not ignored:
        return
    # Only now pay for the explanation: which rule is doing it.
    why = subprocess.run(
        ["git", "check-ignore", "--stdin", "--verbose"],
        cwd=ROOT, input="\n".join(ignored), capture_output=True, text=True,
    ).stdout
    raise AssertionError(
        "these source files are ignored by .gitignore, so `git add` will refuse them and the "
        "commit will succeed without them:\n" + why
    )
