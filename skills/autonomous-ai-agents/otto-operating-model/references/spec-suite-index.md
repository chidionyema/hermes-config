# Spec Suite Index

Maps every spec in `~/.hermes/specs/otto-system/` to its implementation scripts and status.

| # | Spec File | Script(s) | Status |
|---|-----------|-----------|--------|
| 00 | 00-MASTER.md | (all) | ✅ Written |
| 01 | 01-correction-learning-loop.md | `policy-enforcer.py`, `reflect-on-correction.py`, `otto-learn.py` | ✅ Written |
| 02 | 02-dispatch-gate.md | `dispatch_gate.py` | ✅ Written |
| 03 | 03-memory-retrieval.md | `memory_retrieval.py` | ✅ Written |
| 04 | 04-idle-consolidation.md | `idle-consolidation.py` | ✅ Written |
| 05 | 05-self-regression.md | `self-regression.py` | ✅ Written |
| 06 | 06-gap-finding.md | `gap-finding.py` | ✅ Written |
| 07 | 07-dna-specimen.md | (conceptual) | ✅ Written |
| 08 | 08-goetic-piece.md | `meta-improver.py` (safety) | ✅ Written |
| 09 | 09-idle-continuous-learning.md | `idle-learning-run.sh` | ✅ Written |
| 10 | 10-exponential-self-improvement.md | `meta-improver.py` | ✅ Written (awaiting Opus review) |
| — | policy-enforcer-redesign.md | `policy-enforcer.py` | ✅ Written |

**Other related files:**
- `~/.hermes/scripts/post-claim-verifier.py` — post-claim evidence checker
- `~/.hermes/policies/pol-*.json` — 8 correction policies (see `01-correction-learning-loop.md`)
- `~/.hermes/cron/jobs.json` — 10 scheduled jobs (see `09-idle-continuous-learning.md`)
