"""skill-hygiene + memory-hygiene probes (Item 6)."""
import subprocess
import sys

from conftest import SCRIPTS

SKILL = str(SCRIPTS / "skill-hygiene.py")
MEM = str(SCRIPTS / "memory-hygiene.py")


def _mk_skill(root, name, body="x"):
    d = root / "skills" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\n---\n{body}\n")
    return d


def test_orphan_skill_flagged(hermes_env, monkeypatch):
    path, env = hermes_env
    _mk_skill(path, "lonely-skill")
    # backdate the SKILL.md beyond the orphan window
    import os, time
    old = time.time() - 30 * 86400
    os.utime(path / "skills" / "lonely-skill" / "SKILL.md", (old, old))
    r = subprocess.run([sys.executable, SKILL], capture_output=True, text=True,
                       env={**env, "HERMES_SKILL_ORPHAN_DAYS": "14"})
    assert r.returncode == 1 and "lonely-skill" in r.stdout


def test_wired_skill_passes(hermes_env):
    path, env = hermes_env
    _mk_skill(path, "wired-skill")
    # a SECOND skill references it -> wired. (scripts/ is symlinked to the real dir in
    # the fixture, so use another skill under the tmp skills/ tree as the referrer.)
    _mk_skill(path, "referrer-skill", body="this builds on wired-skill")
    import os, time
    old = time.time() - 30 * 86400
    os.utime(path / "skills" / "wired-skill" / "SKILL.md", (old, old))
    r = subprocess.run([sys.executable, SKILL], capture_output=True, text=True,
                       env={**env, "HERMES_SKILL_ORPHAN_DAYS": "14"})
    assert r.returncode == 0, r.stdout


def test_recent_skill_not_flagged(hermes_env):
    path, env = hermes_env
    _mk_skill(path, "fresh-skill")  # just created -> within window
    r = subprocess.run([sys.executable, SKILL], capture_output=True, text=True, env=env)
    assert r.returncode == 0


def _mem(path, text):
    (path / "memories").mkdir(parents=True, exist_ok=True)
    (path / "memories" / "MEMORY.md").write_text(text)


def test_unverified_memory_flagged(hermes_env):
    path, env = hermes_env
    _mem(path, "fact one, no stamp\n§\nfact two [verified: 2099-01-01]\n")
    r = subprocess.run([sys.executable, MEM], capture_output=True, text=True, env=env)
    assert r.returncode == 1 and "1 unstamped" in r.stdout


def test_all_verified_memory_passes(hermes_env):
    path, env = hermes_env
    _mem(path, "fact [verified: 2099-01-01]\n§\nother [verified: 2099-02-02]\n")
    r = subprocess.run([sys.executable, MEM], capture_output=True, text=True, env=env)
    assert r.returncode == 0
