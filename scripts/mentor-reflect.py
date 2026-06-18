#!/usr/bin/env python3
"""mentor-reflect — Claude is Otto's permanent mentor (continuous, not session-bound).

Wired to Otto's session-start. It gathers the recent failure record (dropped balls,
escalations, open loops), asks Claude (sonnet — cheap, per the routing ladder) the one
question that matters — "what should Otto learn from this?" — and turns the answer into
SUBSTRATE, not journaling:

  1. appends the lesson to memories/MEMORY.md, stamped [verified: today] (read-back
     verified, per the balls-6+15 memory-write rule), and
  2. submits a reflection fingerprint to the relay queue (source mentor-reflection).
     The dropped-ball-style probe fires if that fingerprint is unresolved after 24h, so
     a lesson with no follow-through (a probe/skill change) becomes a tracked open loop
     instead of a forgotten log line. Reflection == behaviour change.

A proposed skill patch is written to logs/reflection/ for Claude/human review — the
mentor never blind-edits skills (that is the self-certification anti-pattern).

Test seam: HERMES_MENTOR_FAKE supplies the model answer instead of calling the CLI, so
the probe runs deterministically and free.
"""
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timezone

HERMES = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
SCRIPTS = os.path.join(HERMES, "scripts")
QUEUE_CLI = os.path.join(SCRIPTS, "hermes_queue.py")
MEMORY = os.path.join(HERMES, "memories", "MEMORY.md")
REFLECT_DIR = os.path.join(HERMES, "logs", "reflection")
TODAY = date.today().isoformat()

PROMPT_TMPL = """You are Claude, the permanent mentor of an autonomous agent named Otto.
Here is Otto's recent failure record:

{context}

In ONE lesson, what should Otto learn to stop repeating these? Respond with STRICT JSON:
{{"lesson": "<one sentence>", "memory_line": "<<=200 chars, an imperative rule>",
  "probe_idea": "<one sentence: what probe would catch a regression>",
  "skill_hint": "<which skill to patch and how, one sentence>"}}"""


def _gather_context():
    parts = []
    try:
        r = subprocess.run(["python3", QUEUE_CLI, "status"], capture_output=True,
                           text=True, timeout=20, env={**os.environ, "HERMES_HOME": HERMES})
        d = json.loads(r.stdout)
        parts.append("open_loops=%d" % d.get("open_fingerprints", 0))
        parts.append("dropped_balls_by_source=%s" % json.dumps(d.get("dropped_ball_by_source", {})))
    except Exception:
        parts.append("(queue status unavailable)")
    return "\n".join(parts) or "(no failures recorded)"


def _ask_claude(prompt):
    fake = os.environ.get("HERMES_MENTOR_FAKE")
    if fake is not None:
        return fake
    try:
        r = subprocess.run(["claude", "-p", prompt, "--model", "sonnet"],
                           capture_output=True, text=True, timeout=180)
        return r.stdout
    except Exception as e:
        return '{"error": "%s"}' % str(e)[:80]


def _extract_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _append_memory(line):
    """Append one verified rule to MEMORY.md, read-back verified. True if persisted."""
    stamped = "%s [verified: %s]" % (line.rstrip("."), TODAY)
    os.makedirs(os.path.dirname(MEMORY), exist_ok=True)
    existing = ""
    if os.path.exists(MEMORY):
        existing = open(MEMORY).read()
        if line[:40] in existing:        # already learned this — idempotent
            return True
    with open(MEMORY, "a") as f:
        f.write(("\n§\n" if existing.strip() else "") + stamped + "\n")
    return stamped in open(MEMORY).read()  # read-back verify


def _submit_reflection(lesson):
    if not os.path.exists(QUEUE_CLI):
        return
    try:
        subprocess.run(["python3", QUEUE_CLI, "submit", "--source", "mentor-reflection",
                        "--severity", "warn", "--fingerprint", "mentor-lesson-%s" % TODAY,
                        "--message", "mentor lesson needs a probe/skill follow-through: " + lesson[:120]],
                       capture_output=True, text=True, timeout=20,
                       env={**os.environ, "HERMES_HOME": HERMES})
    except Exception:
        pass


def main():
    ans = _ask_claude(PROMPT_TMPL.format(context=_gather_context()))
    obj = _extract_json(ans)
    if not obj or "memory_line" not in obj:
        print("mentor-reflect: no usable lesson (model answer unparseable)", file=sys.stderr)
        return 1
    persisted = _append_memory(obj["memory_line"])
    _submit_reflection(obj.get("lesson", obj["memory_line"]))
    os.makedirs(REFLECT_DIR, exist_ok=True)
    with open(os.path.join(REFLECT_DIR, "mentor-%s.md" % TODAY), "a") as f:
        f.write("## %s\n- lesson: %s\n- memory(persisted=%s): %s\n- probe_idea: %s\n- skill_hint: %s\n\n"
                % (datetime.now(timezone.utc).isoformat(), obj.get("lesson", ""),
                   persisted, obj["memory_line"], obj.get("probe_idea", ""), obj.get("skill_hint", "")))
    if not persisted:
        print("mentor-reflect: memory write FAILED read-back (ball 6/15 class)", file=sys.stderr)
        return 2
    return 0  # silent on success


if __name__ == "__main__":
    sys.exit(main())
