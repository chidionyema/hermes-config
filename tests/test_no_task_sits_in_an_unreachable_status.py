"""Every task status must be either ACTIVE (the tick picks it up) or TERMINAL (it is closed).

A status in neither is a leak with no alarm on it: the coordinator never works the row and no
rollup ever counts it. MEASURED 2026-08-19: 236 rows sit in status='failed' and 1 in
'cancelled', neither of which appears in ACTIVE or TERMINAL. Nothing writes 'failed' any more
(the only mention left is requeue_failed.py, the tool for digging them back out), so these are
the residue of a retired status — invisible debt that reads as neither open nor done.
"""
import os, sqlite3, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import coordinator as C

DB = os.path.expanduser("~/.hermes/coordinator.db")


class StatusInvariant(unittest.TestCase):
    def test_the_two_sets_cover_every_status_the_code_can_write(self):
        """The invariant itself, checkable without a database."""
        self.assertEqual(set(C.ACTIVE) & set(C.TERMINAL), set(),
                         "a status cannot be both worked and closed")

    @unittest.skipUnless(os.path.exists(DB), "no live coordinator.db on this machine")
    def test_no_live_row_sits_outside_both_sets(self):
        known = set(C.ACTIVE) | set(C.TERMINAL)
        conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        orphans = [(s, n) for s, n in
                   conn.execute("select status, count(*) from tasks group by status")
                   if s not in known]
        conn.close()
        self.assertFalse(orphans,
                         "tasks parked in a status the coordinator neither works nor counts "
                         f"as closed: {orphans}. Either add the status to ACTIVE/TERMINAL or "
                         "migrate the rows (scripts/requeue_failed.py digs 'failed' back out).")


if __name__ == "__main__":
    unittest.main()
