"""A silent exit-0 acceptance test must not close a task the executor could not act on.

2026-08-18: task c53a1e4b2841 closed `done` with the reason "acceptance test passed (ground
truth); fingerprint resolved. (exit 0, no output)". Its evidence was
`[executor-narrative-fallback (claude: timeout after 900s; reasoning via minimax/MiniMax-M3)]`
followed by MiniMax printing its tool calls as prose — it has no tool runtime, so it changed
nothing. The acceptance test was
`python3 ~/.hermes/tests/test_resilience_ticks_unreadable.py >/dev/null 2>&1 && grep -q ... `,
silent by construction and true whether or not this run did the work.
"""
import json, os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import coordinator as C


def _task(evidence, acc):
    return {"result": evidence, "spec": json.dumps({"acceptance_test": acc}),
            "kind": "failure", "source": "failure:x", "domain": ""}


class SilentAcceptance(unittest.TestCase):
    def setUp(self):
        self._run = C._run_acceptance
        self._res = C._resolve_fingerprint
        C._resolve_fingerprint = lambda s: None

    def tearDown(self):
        C._run_acceptance = self._run
        C._resolve_fingerprint = self._res

    def test_silent_pass_plus_chat_fallback_is_refused(self):
        C._run_acceptance = lambda a: (True, "(exit 0, no output)")
        ok, why = C.verify(_task("[executor-narrative-fallback (claude: timeout after 900s)]\nDONE.",
                                 "grep -q MARKER file"), None, lambda t: False)
        self.assertFalse(ok, why)
        self.assertIn("no output is not proof", why)

    def test_a_talking_acceptance_test_still_closes_the_task(self):
        """The fix must not pin real fixes open. A check that REPORTS what it saw is evidence."""
        C._run_acceptance = lambda a: (True, "signalengine: pass rc 0 secs 17.6")
        ok, _ = C.verify(_task("[executor-narrative-fallback (claude: timeout after 900s)]\nDONE.",
                               "grep -q MARKER file"), None, lambda t: False)
        self.assertTrue(ok)

    def test_silent_pass_on_real_tool_work_still_closes_the_task(self):
        """Silence alone is not the defect — silence plus 'the executor could not act' is."""
        C._run_acceptance = lambda a: (True, "(exit 0, no output)")
        ok, _ = C.verify(_task("Edited resilience.py and ran the suite: 41 passed.",
                               "grep -q MARKER file"), None, lambda t: False)
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
