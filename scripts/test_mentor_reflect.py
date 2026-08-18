#!/usr/bin/env python3
"""Acceptance probe for the mentor-reflect CRON_ERROR fix.

The failure: `CRON_ERROR: mentor-reflect errored: Script exited with code 1 /
mentor-reflect: no usable lesson (model answer unparseable)`.

The nested `claude -p` inherits the global CLAUDE.md house style and regularly answers in
prose ("BLOCKED: ...") instead of JSON. The script treated that as a hard error.

These tests pin the fixed contract:
  - model answers prose            -> exit 0, raw answer logged (was exit 1 = CRON_ERROR)
  - fenced / prose-wrapped / nested-brace JSON parses
  - the CLI genuinely breaking     -> still exit 1 (the alarm keeps its teeth)
  - happy path still writes memory

Run: python3 ~/.hermes/scripts/test_mentor_reflect.py    (exit 0 = all pass)
"""
import os
import subprocess
import sys
import tempfile
from datetime import date

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mentor-reflect.py")
TODAY = date.today().isoformat()
results = []


def run(fake=None, path_prepend=None):
    home = tempfile.mkdtemp()
    env = {**os.environ, "HERMES_HOME": home}
    if fake is not None:
        env["HERMES_MENTOR_FAKE"] = fake
    else:
        env.pop("HERMES_MENTOR_FAKE", None)
    if path_prepend:
        env["PATH"] = path_prepend + os.pathsep + env["PATH"]
    r = subprocess.run([sys.executable, SCRIPT], capture_output=True, text=True,
                       timeout=300, env=env)
    return home, r


def check(name, cond, detail=""):
    results.append((name, cond, detail))
    print("%s [%s] %s" % ("PASS" if cond else "FAIL", name, detail))


def read(p):
    try:
        return open(p).read()
    except Exception:
        return ""


# T1 — the EXACT prose that produced the reported CRON_ERROR.
PROSE = ("BLOCKED: the nested `claude -p` call refused to fabricate the JSON - no real event "
         "exists yet to fill `lesson`/`memory_line`/`probe_idea`/`skill_hint` with, so it asked "
         "whether you wanted (1) it to just run the script (read-only, no side effects) or "
         "(2) it to answer the schema against a specific real incident you point it at.")
home, r = run(fake=PROSE)
check("prose-refusal-exit", r.returncode == 0, "exit=%d (was 1) stderr=%r" % (r.returncode, r.stderr[:120]))
log = read(os.path.join(home, "logs", "reflection", "mentor-%s.md" % TODAY))
check("prose-refusal-audited", "NO LESSON" in log and "refused to fabricate" in log,
      "raw answer written to logs/reflection, not swallowed")

# T2 — fenced JSON.
home, r = run(fake='```json\n{"lesson":"L","memory_line":"M","probe_idea":"P","skill_hint":"S"}\n```')
check("fenced-json", r.returncode == 0 and "M [verified:" in read(os.path.join(home, "memories", "MEMORY.md")),
      "exit=%d" % r.returncode)

# T3 — prose around JSON that itself contains nested braces (greedy `\{.*\}` mishandled this).
home, r = run(fake='Here is my answer.\n{"lesson":"L","memory_line":"M2","probe_idea":"P",'
                   '"skill_hint":"S","meta":{"a":{"b":1}}}\nHope that helps!')
check("prose-plus-nested-braces", r.returncode == 0 and "M2 [verified:" in read(os.path.join(home, "memories", "MEMORY.md")),
      "exit=%d" % r.returncode)

# T4 — a decoy brace before the real object; the first `{` candidate must be skipped.
home, r = run(fake='Use {curly} braces like: {"lesson":"L","memory_line":"M3","probe_idea":"P","skill_hint":"S"}')
check("decoy-brace-before-json", r.returncode == 0 and "M3 [verified:" in read(os.path.join(home, "memories", "MEMORY.md")),
      "exit=%d" % r.returncode)

# T5 — the CLI itself failing must STILL exit 1. The fix must not blanket-swallow errors.
bindir = tempfile.mkdtemp()
stub = os.path.join(bindir, "claude")
with open(stub, "w") as f:
    f.write("#!/bin/sh\necho 'boom' >&2\nexit 7\n")
os.chmod(stub, 0o755)
home, r = run(fake=None, path_prepend=bindir)
check("broken-cli-still-errors", r.returncode == 1 and "model call failed" in r.stderr,
      "exit=%d stderr=%r" % (r.returncode, r.stderr.strip()[:120]))

# T6 — happy path unchanged: memory written and read-back verified.
home, r = run(fake='{"lesson":"L","memory_line":"Do the thing","probe_idea":"P","skill_hint":"S"}')
check("happy-path", r.returncode == 0 and "Do the thing [verified:" in read(os.path.join(home, "memories", "MEMORY.md")),
      "exit=%d" % r.returncode)

failed = [n for n, ok, _ in results if not ok]
print("\nACCEPTANCE: %d/%d pass%s" % (len(results) - len(failed), len(results),
                                      "" if not failed else "  FAILED: " + ", ".join(failed)))
sys.exit(1 if failed else 0)
