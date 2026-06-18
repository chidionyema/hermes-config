# Build Note 06 — Gap-Finding

*Part of the Otto system. See 00-MASTER.md for the architectural context.*

## What it is

Scans the failure corpus + capability registry for domains where Otto repeatedly stumbles and has no skill or policy covering it. Surfaces these as ranked build candidates. Otto identifies the gap; you decide what to build.

## Implementation

**File:** `~/.hermes/scripts/gap-finding.py`

**How it works:**
1. Scans failure corpus (extracts domain keywords from each entry)
2. Counts how many failures per domain
3. Checks each domain against known coverage: policies + skills + builtin capabilities
4. Reports: uncovered domains (🔴) and weak-coverage domains (🟡)
5. Output: `~/.hermes/logs/maintenance/gaps-YYYY-MM-DD.md`

**Builtin capabilities checked:** terminal, file I/O, web search, browser, git, skill management, cron, delegation, memory, session search, code execution, vision, image gen, TTS, messaging.

**Why gap-finding exists:** Without it, blind spots persist. A failure that has no corresponding policy or skill will keep recurring until manually noticed. Gap-finding automates the discovery.
