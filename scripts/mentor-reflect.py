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


# The nested `claude -p` inherits the global CLAUDE.md (ANSWER FIRST + proof discipline),
# which regularly makes it answer in prose ("BLOCKED: ...") instead of the JSON this script
# parses. That prose was the daily CRON_ERROR. This system prompt overrides the chatty
# house style for this one call.
JSON_ONLY_SYSTEM = (
    "You are answering a machine, not a human. Output the raw JSON object and NOTHING else: "
    "no preamble, no status line, no receipts, no code fences, no trailing commentary. "
    "The input is a summary of counters, so it is complete on its own — do not ask for more "
    "context and do not refuse. Your entire stdout must parse as one JSON object."
)


def _ask_claude(prompt):
    """Return (text, cli_ok). cli_ok is False only when the CLI itself failed."""
    fake = os.environ.get("HERMES_MENTOR_FAKE")
    if fake is not None:
        return fake, True
    try:
        r = subprocess.run(["claude", "-p", prompt, "--model", "sonnet",
                            "--append-system-prompt", JSON_ONLY_SYSTEM],
                           capture_output=True, text=True, timeout=180)
    except Exception as e:
        return "claude CLI raised: %s" % str(e)[:200], False
    if r.returncode != 0:
        return "claude CLI exited %d: %s" % (r.returncode, (r.stderr or "")[:200]), False
    if not r.stdout.strip():
        return "claude CLI produced empty stdout (stderr: %s)" % (r.stderr or "")[:200], False
    return r.stdout, True


def _extract_json(text):
    """Find the first balanced {...} that parses. Tolerates fences and surrounding prose."""
    if not text:
        return None
    text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip(), flags=re.M)
    for start in (i for i, c in enumerate(text) if c == "{"):
        depth, in_str, esc = 0, False, False
        for end in range(start, len(text)):
            c = text[end]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:end + 1])
                    except Exception:
                        break          # this candidate is not valid JSON; try the next '{'
                    if isinstance(obj, dict):
                        return obj
                    break
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


def _log_unparsed(ans):
    """Keep the raw answer auditable — a skipped lesson must not vanish silently."""
    try:
        os.makedirs(REFLECT_DIR, exist_ok=True)
        with open(os.path.join(REFLECT_DIR, "mentor-%s.md" % TODAY), "a") as f:
            f.write("## %s\n- NO LESSON: model answered without usable JSON\n- raw: %s\n\n"
                    % (datetime.now(timezone.utc).isoformat(), (ans or "")[:600].replace("\n", " ")))
    except Exception:
        pass


def main():
    prompt = PROMPT_TMPL.format(context=_gather_context())
    ans, cli_ok = _ask_claude(prompt)
    if not cli_ok:
        # The CLI itself broke (missing, timed out, nonzero, empty). That IS a real failure.
        print("mentor-reflect: model call failed: %s" % ans[:200], file=sys.stderr)
        return 1
    obj = _extract_json(ans)
    if not obj or "memory_line" not in obj:
        # One strict retry; the first answer was prose, not a broken CLI.
        ans2, cli_ok2 = _ask_claude(
            prompt + "\n\nYour previous answer was not valid JSON. Output ONLY the JSON object, "
                     "starting with { and ending with }. No other characters.")
        if cli_ok2:
            obj = _extract_json(ans2)
            ans = ans2
    if not obj or "memory_line" not in obj:
        # Model reachable but declined to produce a lesson. Not a job failure — record and
        # exit clean so a chatty model stops raising a daily CRON_ERROR.
        _log_unparsed(ans)
        print("mentor-reflect: no usable lesson this run (model answered without JSON); "
              "raw answer logged to %s" % REFLECT_DIR)
        return 0
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
