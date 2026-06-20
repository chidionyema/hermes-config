#!/usr/bin/env python3
"""claude_handback_gate — stop Otto from self-fixing an issue Claude already owns.

ROOT CAUSE (coordination failure, 2026-06-20)
---------------------------------------------
Otto had no pre-action check for an existing Claude dispatch. When repo-health escalated
"signalengine pytest hangs", a live `otto-claude-signalengine` tmux session had ALREADY handed
back the fix (commit fddef58, full suite 149s -> 35s; root cause: heavy fitter tests weren't
marked @slow). Otto, blind to that session, jumped to proposing its own — WRONG — fix: raise the
repo-health timeout (which would have masked the symptom and left the slow tests in the fast gate).

THE GATE
--------
Before Otto self-fixes or escalates an issue, check whether a live `otto-claude-<topic>` tmux
session's topic matches the issue. Verdicts:

  handback  session live AND a handback marker (commit SHA / completion phrase) is visible in the
            pane  ->  surface Claude's receipt, NEVER self-fix.
  inflight  session live, no handback marker yet                    ->  HOLD, never self-fix
            (in-flight != stalled; do not race a dispatched agent).
  clear     no live session matches the issue topic                 ->  Otto proceeds as normal.

This is the structural form of the wait-for-handback rule: a MECHANISM Otto must pass through,
not a convention it is asked to remember. `clear` is the only verdict that lets Otto act.

Defensive by construction: any error (no tmux, capture failure, parse error) degrades to `clear`
so the gate can NEVER break the dispatcher (which runs under a hard cron budget). Failing open is
correct here — the gate only ever SUPPRESSES Otto; a false `clear` just restores today's behaviour.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys

# Convention: Claude is dispatched on a topic in a tmux session named `otto-claude-<topic>`.
SESSION_PREFIX = "otto-claude-"
# Topic must have at least this many alnum chars to match, so a tiny/empty topic can't match
# every issue and silence Otto wholesale.
_MIN_TOPIC_LEN = 4
# How many trailing pane lines to scan for a handback marker.
_PANE_LINES = 200

# Handback markers, strongest first. A commit SHA is the canonical receipt; completion phrases are
# the fallback when the pane has scrolled past the commit line. A SHA line is one that carries a
# commit/landed keyword AND a 7-40 char hex token (which may be separated by words like "as"/"in",
# e.g. "Committed as `fddef58`"). The keyword guard keeps a bare hex-looking token from matching.
_COMMIT_KW_RE = re.compile(r"\b(commit|committed|landed|sha|fix(?:ed)?)\b", re.IGNORECASE)
_HEX_RE = re.compile(r"\b([0-9a-f]{7,40})\b")
_PHRASE_RE = re.compile(
    r"(safe point|co-authored-by|handed back|handback|all (?:tests|checks) pass|"
    r"\bdone\b.*\bpass|✅|verified.*pass)",
    re.IGNORECASE,
)


def _norm(s: str) -> str:
    """Lowercase and strip to [a-z0-9] so 'signal-engine' / 'signal_engine' / 'Signalengine'
    all collapse to the same token for substring matching."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def live_claude_sessions(runner=subprocess.run) -> list[tuple[str, str]]:
    """Return [(session_name, topic)] for every live `otto-claude-*` tmux session.

    `topic` is the session name with the `otto-claude-` prefix stripped. Returns [] on any failure
    (no tmux server, command error, timeout) — fail open.
    """
    try:
        p = runner(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return []
    if p.returncode != 0:
        return []
    out = []
    for line in (p.stdout or "").splitlines():
        name = line.strip()
        if name.startswith(SESSION_PREFIX):
            topic = name[len(SESSION_PREFIX):]
            out.append((name, topic))
    return out


def capture_pane(session: str, runner=subprocess.run) -> str:
    """Return the trailing pane text of `session`, or '' on any failure."""
    try:
        p = runner(
            ["tmux", "capture-pane", "-t", session, "-p", "-S", f"-{_PANE_LINES}"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return ""
    return p.stdout if p.returncode == 0 else ""


def find_handback(pane: str) -> str | None:
    """Scan pane text for a handback marker. Return a short receipt string, or None.

    Prefers a commit SHA (the canonical receipt); falls back to a completion phrase. The receipt
    is the matched line, trimmed — enough for Otto to surface 'Claude already landed X'.
    """
    if not pane:
        return None
    lines = pane.splitlines()
    # Strongest signal: a line carrying both a commit/landed keyword and a hex SHA token. The hex
    # token must contain at least one a-f letter so a 7+ digit decimal can't masquerade as a SHA.
    for line in reversed(lines):
        if not _COMMIT_KW_RE.search(line):
            continue
        for tok in _HEX_RE.findall(line):
            if any(c in "abcdef" for c in tok):
                return _receipt(line, sha=tok)
    # Fallback: an explicit completion phrase.
    for line in reversed(lines):
        if _PHRASE_RE.search(line):
            return _receipt(line)
    return None


def _receipt(line: str, sha: str | None = None) -> str:
    text = " ".join(line.split())  # collapse whitespace / TUI padding
    if len(text) > 160:
        text = text[:157] + "..."
    return (f"commit {sha}: {text}" if sha and sha not in text else text) if sha else text


def _topic_matches(topic: str, haystack: str) -> bool:
    nt = _norm(topic)
    if len(nt) < _MIN_TOPIC_LEN:
        return False
    return nt in _norm(haystack)


def check_issue(
    source: str = "",
    sample: str = "",
    fingerprint: str = "",
    *,
    sessions: list[tuple[str, str]] | None = None,
    pane_text: str | None = None,
    runner=subprocess.run,
) -> dict:
    """Classify one issue against live Claude dispatches.

    Args:
        source/sample/fingerprint: the issue's identifying text (any/all may be empty).
        sessions: inject [(name, topic)] to bypass live tmux (tests); None -> query tmux.
        pane_text: inject pane text to bypass capture (tests); None -> capture live.

    Returns {verdict, session, topic, receipt}. verdict is one of clear|inflight|handback.
    Only 'clear' permits Otto to act. Never raises — degrades to clear.
    """
    try:
        haystack = f"{source} {sample} {fingerprint}"
        sess = live_claude_sessions(runner) if sessions is None else sessions
        match = next(((n, t) for (n, t) in sess if _topic_matches(t, haystack)), None)
        if not match:
            return {"verdict": "clear", "session": None, "topic": None, "receipt": None}
        name, topic = match
        pane = capture_pane(name, runner) if pane_text is None else pane_text
        receipt = find_handback(pane)
        verdict = "handback" if receipt else "inflight"
        return {"verdict": verdict, "session": name, "topic": topic, "receipt": receipt}
    except Exception:
        # Fail open: the gate must never crash the coordinator.
        return {"verdict": "clear", "session": None, "topic": None, "receipt": None}


def claude_owns(source: str = "", sample: str = "", fingerprint: str = "", **kw) -> bool:
    """True iff Otto must NOT act on this issue (Claude is dispatched: handback or inflight)."""
    return check_issue(source, sample, fingerprint, **kw)["verdict"] != "clear"


# --------------------------------------------------------------------------------------------
# Self-test: replays the exact 2026-06-20 failure and proves the gate would have caught it.
# --------------------------------------------------------------------------------------------
def _self_test() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool) -> None:
        if not cond:
            failures.append(name)

    # The failure as it actually fired: repo-health escalates the signalengine pytest hang while a
    # live `otto-claude-signalengine` session has already handed back commit fddef58.
    sessions = [("otto-claude-signalengine", "signalengine"),
                ("otto-claude-cron-fixes", "cron-fixes")]
    pane_handback = (
        "Done. Committed as `fddef58`.\n"
        "Default suite 303 passed in 35.53s (down from 148.65s).\n"
        "Co-Authored-By: Claude\n"
        "Safe point — type /clear.\n"
    )
    r = check_issue(
        source="repo-health",
        sample="signalengine: pytest -q: TIMEOUT (> 90s)",
        sessions=sessions, pane_text=pane_handback,
    )
    check("THE failure -> handback", r["verdict"] == "handback")
    check("THE failure -> right session", r["session"] == "otto-claude-signalengine")
    check("THE failure -> receipt carries fddef58", r["receipt"] and "fddef58" in r["receipt"])
    check("THE failure -> Otto must NOT act", claude_owns(
        "repo-health", "signalengine: pytest -q: TIMEOUT (> 90s)",
        sessions=sessions, pane_text=pane_handback))

    # Matching is separator-insensitive: signal-engine-watchdog must match topic 'signalengine'.
    r2 = check_issue("signal-engine-watchdog", "signal_engine.daemon not running",
                     sessions=sessions, pane_text=pane_handback)
    check("separator-insensitive match", r2["verdict"] == "handback")

    # In-flight (session live, no handback marker in pane yet) -> hold, still must NOT act.
    r3 = check_issue("repo-health", "signalengine: pytest -q: TIMEOUT (> 90s)",
                     sessions=sessions, pane_text="Running durations profile...\n")
    check("inflight verdict", r3["verdict"] == "inflight")
    check("inflight -> Otto must NOT act", r3["verdict"] != "clear")

    # No matching session -> clear (Otto proceeds; we don't suppress unrelated issues).
    r4 = check_issue("repo-health", "someotherproject: lint failure",
                     sessions=sessions, pane_text=pane_handback)
    check("unrelated issue -> clear", r4["verdict"] == "clear")

    # A tiny/empty topic must not match everything.
    r5 = check_issue("repo-health", "anything at all",
                     sessions=[("otto-claude-x", "x")], pane_text="")
    check("tiny topic does not match", r5["verdict"] == "clear")

    # No sessions at all -> clear (degrade to today's behaviour).
    r6 = check_issue("repo-health", "signalengine: pytest hang",
                     sessions=[], pane_text="")
    check("no sessions -> clear", r6["verdict"] == "clear")

    if failures:
        print("SELF-TEST FAILED:")
        for f in failures:
            print(f"  ✗ {f}")
        return 1
    print("SELF-TEST PASSED (7 checks): the gate catches the 2026-06-20 signalengine failure.")
    return 0


_EXIT = {"clear": 0, "handback": 10, "inflight": 11}


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Check whether Claude already owns an issue.")
    ap.add_argument("--source", default="")
    ap.add_argument("--sample", default="")
    ap.add_argument("--fingerprint", default="")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    r = check_issue(a.source, a.sample, a.fingerprint)
    print(json.dumps(r))
    # Exit code lets bash callers branch: 0 clear (act), 10 handback (defer), 11 inflight (hold).
    return _EXIT.get(r["verdict"], 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
