"""End-to-end probe: drives the REAL timeout path (exit code 124) through main().

Nothing about check_repo is stubbed — a repo whose test_cmd is `sleep 30` under a
2s PER_REPO_TIMEOUT reproduces the 12:49:03Z tick for real. Only submit() is
stubbed, so no page can escape to the relay queue.
"""
import importlib.util
import json
import os
import pathlib
import tempfile

os.environ["HERMES_REPO_TIMEOUT"] = "2"
tmp = pathlib.Path(tempfile.mkdtemp())
os.environ["HERMES_HOME"] = str(tmp / "hermes")

src = pathlib.Path.home() / ".hermes" / "scripts" / "repo-health-check.py"
spec = importlib.util.spec_from_file_location("rhc", src)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

(tmp / "slowrepo").mkdir()
m.LOG_DIR = tmp / "health"
m.HISTORY_FILE = m.LOG_DIR / "repo-health.jsonl"
m.LOG_DIR.mkdir(parents=True, exist_ok=True)
m.QUEUE = tmp / "no-such-queue.py"
m.REPOS = {"lux": {"path": str(tmp / "slowrepo"), "requires": [], "test_cmd": "sleep 30"}}

pages = []
m.submit = lambda msg, sev: pages.append((sev, msg))

print("PER_REPO_TIMEOUT =", m.PER_REPO_TIMEOUT)
# Seed a green previous tick, exactly like the 12:35:19Z entry.
m.HISTORY_FILE.write_text(json.dumps(
    {"timestamp": "seed", "results": {"lux": {"state": "pass", "summary": "lux: tests pass"}}}) + "\n")

print("--- tick 1 (the 12:49:03Z scenario: first slow tick) ---")
rc = m.main()
print("exit:", rc, "| pages:", pages)
assert rc == 0, rc
assert pages == [], f"REGRESSION: first slow tick still paged: {pages}"

print("--- tick 2 (second consecutive timeout = real regression) ---")
rc = m.main()
print("exit:", rc, "| pages:", pages)
assert len(pages) == 1 and pages[0][0] == "warn", pages

print("--- history recorded BOTH timeouts (suppressed paging, not hidden state) ---")
for line in m.HISTORY_FILE.read_text().splitlines():
    e = json.loads(line)
    print("  ", e["timestamp"], e["results"]["lux"])

print("END-TO-END: OK")
