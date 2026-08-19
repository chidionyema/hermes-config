"""Every large directory here is either shipped on purpose or ignored on purpose.

Measured 2026-08-19 during a release: `fly deploy` sends the whole of ~/.hermes to
the build daemon, and the context passed 900 MB and was still climbing after three
and a half minutes. The cause was four local directories nobody had listed in
`.dockerignore` — `backups/` (278 MB), `.worktrees/` (177 MB), `cache/` and
`repomix-output.xml` (72 MB) — none of which `deploy/hermes/` references.

The class this closes: a directory that grows locally silently taxes every deploy,
and nothing says so. This test fails the next time one appears, and the fix is one
line in `.dockerignore` or one line in the allow-list below with a reason.
"""

import subprocess
from fnmatch import fnmatch
from pathlib import Path

import pytest

HERMES = Path.home() / ".hermes"
DOCKERIGNORE = HERMES / ".dockerignore"

# Anything at the top level bigger than this must be accounted for.
BIG_MB = 50

# Shipped on purpose. A reason per entry, because an allow-list without reasons
# becomes a place to hide things.
SHIPPED = {
    "hermes-agent": "the agent itself; its venv and node_modules are excluded separately",
    "skills": "the 24 installed skills are what the agent runs",
    "models": "miniLM-onnx, the memory embedding model. Retrieval falls back to tag "
              "matching without it, which is the state we are trying to leave",
    "lsp": "code intelligence the agent uses; almost all of its bulk is node_modules, "
           "which **/node_modules already excludes from the context",
}


def _is_ignored(name: str) -> bool:
    """Does .dockerignore exclude this top-level entry?

    Patterns are matched with fnmatch rather than compared literally. An earlier
    version of this helper compared strings, so `*.db` did not match `state.db`
    and the guard accused a 142 MB file that .dockerignore had excluded since
    2026-08-18. A matcher that does not match is a false accusation, which is
    the fastest way to get a guard switched off.
    """
    for raw in DOCKERIGNORE.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        head = line.split("/", 1)[0]
        if not head or head == "**":
            head = line.rstrip("/").rsplit("/", 1)[-1]
        if fnmatch(name, head):
            return True
    return False


def _top_level_sizes_mb() -> dict[str, int]:
    out = subprocess.run(
        ["du", "-sm"] + [str(p) for p in HERMES.iterdir()],
        capture_output=True, text=True, timeout=180,
    ).stdout
    sizes = {}
    for line in out.splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2 and parts[0].strip().isdigit():
            sizes[Path(parts[1]).name] = int(parts[0])
    return sizes


@pytest.mark.skipif(not DOCKERIGNORE.exists(), reason="no .dockerignore")
def test_every_big_directory_is_ignored_or_named():
    unaccounted = {
        name: mb
        for name, mb in _top_level_sizes_mb().items()
        if mb >= BIG_MB and not _is_ignored(name) and name not in SHIPPED
    }
    assert not unaccounted, (
        "these top-level entries are over "
        f"{BIG_MB} MB and are sent to the Docker build daemon on every deploy: "
        + ", ".join(f"{n} ({mb} MB)" for n, mb in sorted(
            unaccounted.items(), key=lambda kv: -kv[1]))
        + ". Add each to .dockerignore, or to SHIPPED in this file with a reason."
    )


def test_the_scan_can_actually_see_something():
    """A guard that measures nothing passes. Prove it read the tree."""
    sizes = _top_level_sizes_mb()
    assert sizes, "du returned nothing — the scan is vacuous"
    assert any(mb >= BIG_MB for mb in sizes.values()), (
        "nothing here is over the threshold, so the check above can never fire"
    )
