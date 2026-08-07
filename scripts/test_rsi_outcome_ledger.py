#!/usr/bin/env python3
"""Proofs for rsi_outcome_ledger — the gate that stops RSI tuning a lever it cannot move.

Every test builds its own temp DB. None of them opens ~/.hermes/coordinator.db for
writing; the one test that reads production opens it read-only and only asserts shape.
(Defect class: memory `tests-polluted-the-production-audit-log.md`.)

Run:  python3 scripts/test_rsi_outcome_ledger.py      (also collects under pytest)
"""

import os
import re
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rsi_outcome_ledger as L  # noqa: E402

HERMES = os.path.expanduser("~/.hermes")
PROD_DB = os.path.join(HERMES, "coordinator.db")


def _mkdb(rows):
    """rows: list of (id, status, result). Returns path to a throwaway DB."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    con = sqlite3.connect(path)
    con.execute("create table tasks (id text, title text, status text, result text,"
                " created_at real, completed_at real)")
    for i, (tid, status, result) in enumerate(rows):
        con.execute("insert into tasks values (?,?,?,?,?,?)",
                    (tid, f"task {tid}", status, result, 1000.0 + i, 2000.0 + i))
    con.commit()
    con.close()
    return path


# ── PROOF 1: the marker tuple is not a second spelling of the producer's ─────────
def test_markers_match_producer():
    """Layer 0: the gate must consume the SAME markers coordinator.py emits.

    The 318-narrated-close incident (coordinator.py:867-871) was exactly this — a gate
    testing a spelling nothing emitted, with tests pinning the dead spelling.
    """
    src = open(os.path.join(HERMES, "scripts", "coordinator.py"), encoding="utf-8").read()
    # Terminate on a line that is exactly ")" — the inline comments contain ")" at
    # end-of-line ("# Tier 2: route.py narrative (279 stored rows)"), so a lazy
    # `.*?\)$` under re.M stops at the first comment and reads ONE marker. That false
    # "drift" is the same shape as the bug this proof exists to catch, so the parser
    # has to be exact or the proof is theatre.
    m = re.search(r"^FALLBACK_MARKERS = \(\n(.*?)^\)$", src, re.S | re.M)
    assert m, "could not locate FALLBACK_MARKERS in coordinator.py"
    produced = tuple(re.findall(r'"([^"]+)"', m.group(1)))
    assert produced == L.FALLBACK_MARKERS, (
        f"ledger markers drifted from producer:\n  producer={produced}\n  ledger  ={L.FALLBACK_MARKERS}")
    print("PROOF 1 ok — markers identical to producer:", produced)


# ── PROOF 2: a cause routes to the lever that could actually remove it ───────────
def test_lever_classification():
    cases = [
        ("[executor-narrative-fallback (claude: timeout after 900s; reasoning via minimax)]"
         " # Report", "done", "executor_timeout"),
        ("[executor-narrative-fallback (claude: exit 1 (session/rate limit); agy: exit 1)]",
         "done", "provider_capacity"),
        ("[executor-narrative-fallback (claude: exit 1 (usage limit reached))]",
         "done", "provider_capacity"),
        ("[executor-unavailable-fallback]\nnothing ran", "done", "observability"),
        ("[agentic-exec-fallback (claude-cli not installed: claude)]", "done", "provider_config"),
        # The executor RAN, produced real output, and the task still failed. The only
        # population a prompt rewrite can reach.
        ("Ran the migration, 4 rows updated, see output above.", "failed", "prompt_quality"),
        ("Ran it, all good.", "done", "ok"),
        ("Escalated after real tool work.", "escalated", "prompt_quality"),
    ]
    for result, status, want in cases:
        got = L.classify_lever(result, status)
        assert got == want, f"{result[:50]!r} -> {got}, want {want}"
    print(f"PROOF 2 ok — {len(cases)} cause->lever mappings correct")


# ── PROOF 3: a timeout mentioned in NARRATIVE prose is not a timeout CAUSE ───────
def test_cause_window_does_not_match_narrative():
    """The scan is bounded to the marker head. An executor that successfully reports
    ON a timeout bug must not be counted as having timed out itself — otherwise the
    ledger inflates the very lever it is used to justify."""
    narrative = "Investigated the cron bug. " + ("x" * 500) + " timeout after 30s was the cause."
    assert L.classify_lever(narrative, "failed") == "prompt_quality"
    # And a real fallback whose cause sits inside the window IS matched.
    assert L.classify_lever("[executor-narrative-fallback (claude: timeout after 900s)] " + narrative,
                            "done") == "executor_timeout"
    print("PROOF 3 ok — cause scan bounded to the marker head, no narrative false-positives")


# ── PROOF 4: attribution math, and prompt_authority is the reachable share ───────
def test_attribution_math():
    db = _mkdb([
        ("a", "done", "[executor-narrative-fallback (claude: timeout after 900s)]"),
        ("b", "done", "[executor-narrative-fallback (claude: timeout after 900s)]"),
        ("c", "done", "[executor-narrative-fallback (claude: exit 1 (session/rate limit))]"),
        ("d", "done", "[executor-unavailable-fallback]"),
        ("e", "failed", "Real tool work, wrong answer."),
        ("f", "done", "Real tool work, right answer."),
    ])
    try:
        a = L.prompt_authority(db)
        assert a["closed_with_result"] == 6, a
        assert a["fallbacks"] == 4, a
        assert a["failures"] == 5, a               # 4 fallbacks + 1 real failure
        assert a["dominant_lever"] == "executor_timeout", a
        assert abs(a["prompt_authority"] - 1 / 5) < 1e-9, a
        levers = {r["lever"]: r["n"] for r in a["by_lever"]}
        assert levers == {"executor_timeout": 2, "provider_capacity": 1,
                          "observability": 1, "prompt_quality": 1}, levers
        print(f"PROOF 4 ok — attribution exact; prompt_authority={a['prompt_authority']:.0%}")
    finally:
        os.unlink(db)


# ── PROOF 5: --since actually partitions, so "since the fix" is answerable ───────
def test_since_filter():
    db = _mkdb([("old", "done", "[executor-narrative-fallback (claude: timeout after 900s)]"),
                ("new", "failed", "Real work, wrong answer.")])
    try:
        assert L.prompt_authority(db)["failures"] == 2
        recent = L.prompt_authority(db, since=2001.0)      # completed_at = 2000, 2001
        assert recent["failures"] == 1, recent
        assert recent["dominant_lever"] == "prompt_quality", recent
        print("PROOF 5 ok — --since partitions the corpus")
    finally:
        os.unlink(db)


# ── PROOF 6: read-only against production; the file is not modified ──────────────
def test_production_db_readonly_and_shaped():
    if not os.path.exists(PROD_DB):
        print("PROOF 6 skipped — no production DB on this host")
        return
    before = (os.path.getmtime(PROD_DB), os.path.getsize(PROD_DB))
    a = L.prompt_authority(PROD_DB)
    after = (os.path.getmtime(PROD_DB), os.path.getsize(PROD_DB))
    assert before == after, "ledger MUTATED the production DB"
    assert a["closed_with_result"] > 0 and a["failures"] > 0, a
    assert 0.0 <= a["prompt_authority"] <= 1.0, a
    assert sum(r["n"] for r in a["by_lever"]) == a["failures"], a
    print(f"PROOF 6 ok — production read-only; {a['failures']} failures, "
          f"dominant={a['dominant_lever']}, prompt_authority={a['prompt_authority']:.1%}")


# ── PROOF 7+8: the gate discriminates, and costs nothing either way ─────────────
def _load_orchestrator():
    import importlib.util
    p = os.path.join(HERMES, "scripts", "rsi-orchestrator.py")
    spec = importlib.util.spec_from_file_location("rsi_orchestrator", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_gate_declines_when_prompt_has_no_authority():
    """rc=3, and it must be reached WITHOUT a strategist call.

    The no-spend property is proved structurally, not by trusting the log: the
    module's own LLM entry point is replaced with a landmine before the call.
    """
    O = _load_orchestrator()
    db = _mkdb([("a", "done", "[executor-narrative-fallback (claude: timeout after 900s)]"),
                ("b", "done", "[executor-narrative-fallback (claude: timeout after 900s)]"),
                ("c", "done", "[executor-narrative-fallback (claude: exit 1 (session/rate limit))]"),
                ("d", "failed", "Real tool work, wrong answer.")])   # authority = 1/4 = 25%
    try:
        O.COORDINATOR_DB = db
        O.RSI_MIN_PROMPT_AUTHORITY = 0.50          # floor above the corpus's 25%
        if hasattr(O, "R"):
            O.R = type("Landmine", (), {
                "route": staticmethod(lambda *a, **k: (_ for _ in ()).throw(
                    AssertionError("strategist called — the gate leaked spend")))})()
        rc = O.run_prompt_tuning("EXECUTE_PROMPT")
        assert rc == 3, f"expected rc=3 (no authority), got {rc}"
        print("PROOF 7 ok — gate returns 3 on a low-authority corpus, no strategist call")
    finally:
        os.unlink(db)


def test_gate_stands_aside_when_prompt_has_authority():
    """Same code path, high-authority corpus -> the gate does NOT fire.

    It must fall through to the ruler-exhaustion preflight (rc=2 on the live
    evalset). A gate that returns 3 unconditionally would pass PROOF 7 and be
    useless; this is the falsifier.
    """
    O = _load_orchestrator()
    db = _mkdb([("a", "failed", "Real tool work, wrong answer."),
                ("b", "failed", "Real tool work, wrong answer."),
                ("c", "done", "[executor-narrative-fallback (claude: timeout after 900s)]")])
    try:
        O.COORDINATOR_DB = db                      # authority = 2/3 = 66.7%
        O.RSI_MIN_PROMPT_AUTHORITY = 0.20
        rc = O.run_prompt_tuning("EXECUTE_PROMPT")
        assert rc != 3, "gate fired despite the prompt having authority"
        assert rc == 2, f"expected fall-through to ruler-exhaustion rc=2, got {rc}"
        print(f"PROOF 8 ok — gate stands aside at 66.7% authority (fell through to rc={rc})")
    finally:
        os.unlink(db)


def test_gate_fires_on_the_REAL_corpus():
    """The live receipt: against production, at the shipped floor, rc must be 3."""
    if not os.path.exists(PROD_DB):
        print("PROOF 9 skipped — no production DB on this host")
        return
    O = _load_orchestrator()
    a = L.prompt_authority(PROD_DB)
    rc = O.run_prompt_tuning("EXECUTE_PROMPT")
    assert rc == 3, f"expected rc=3 on the real corpus, got {rc}"
    print(f"PROOF 9 ok — real corpus: authority {a['prompt_authority']:.1%} < "
          f"{O.RSI_MIN_PROMPT_AUTHORITY:.0%} floor -> rc=3, dominant={a['dominant_lever']}")


def main():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} proofs passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
