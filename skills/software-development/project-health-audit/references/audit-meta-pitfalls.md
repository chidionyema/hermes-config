# Audit Meta-Pitfalls — Probe Resolution Loops, Coverage Noise, Policy Store Saturation

Reference for any periodic health audit (strategist-audit, morning-briefing, weekly repo sweep) that consumes cron state, coverage reports, and policy firings. Captures pitfalls discovered during the 2026-06-19 strategist audit run.

These are **audit-quality** pitfalls, distinct from the project-level health pitfalls in SKILL.md. They describe ways the audit itself can produce misleading or self-defeating output even when the underlying systems are fine.

---

## 1. Probe Resolution Loops (Fingerprint re-opens within one cycle)

**Pattern:** A cron job reports an error. The watchdog's verifier marks the fingerprint `status:"resolved"`. But the cron fires again 30m later with the same error, opening a new row in `watchdog.jsonl` with the same fingerprint. Net effect: `open_fingerprints` count grows by 1 per cycle, masking real new failures in the noise.

**Real-world example (2026-06-19):**
- `repo-health-check` fired `Repo health — 0 pass, 3 fail` every 120m
- Probe marked it resolved at 02:56, 05:02, etc.
- Each cycle re-opened the fingerprint 120m later
- 30 raw `status:"open"` rows accumulated while the latest summary said `open_fingerprints: 3`

**Three structural fixes (pick one):**

(a) **Change cron exit semantics** — make the script exit 0 with structured stdout when the failure is known/expected:
```bash
if [ "$pass_count" -eq 0 ]; then
  echo "Known: 3 repos dirty, awaiting manual clean" >&2
  exit 0  # not exit 1 — this is signal, not failure
fi
```

(b) **Auto-remediate inside the cron script** — when the failure is "X uncommitted files for >24h", have the cron stage them or create a TODO:
```bash
if [ "$uncommitted_count" -gt 50 ]; then
  echo "STAGED_FOR_CLEAN: $uncommitted_count files" > ~/.hermes/state/repo-clean-todo.json
  exit 0
fi
```

(c) **Tighten the watchdog fingerprint regex** — only alert on `exit_code != 0`, never on stdout content. Stdout is for humans; exit codes are for probes. Watchdog should not parse stdout for fingerprints.

**Recommended:** (c). Cleanest separation of concerns. Stdout noise stays informational; exit codes carry signal.

---

## 2. Coverage Report Noise — Duplicates from Health-Bridge Sources

**Pattern:** A periodic health check writes near-identical corpus entries every cycle ("uncommitted work in lux", "uncommitted work in prospector", "uncommitted work in signalengine"). After 24h, the corpus has 60+ entries that all describe the same persistent state. Coverage reports say "8% covered" not because policies are weak, but because the corpus is saturated with one finding repeated.

**Real-world example (2026-06-19):**
- Regression corpus: 88 entries, 81 uncovered
- 60+ entries are `Would policy now prevent uncommitted work in {lux,prospector,signalengine}?` — three near-duplicate questions asked 20+ times
- True distinct failures: ~10-15, not 88

**Fix — dedup before counting:**
```bash
# Strip duplicates by (source, question_stem)
python3 -c "
import json
seen = set()
unique = []
for line in open('~/.hermes/logs/self-regression-corpus.json'):
    d = json.loads(line)
    key = d.get('source','') + ':' + d.get('question','')[:30]
    if key in seen: continue
    seen.add(key)
    unique.append(d)
print(f'Unique entries: {len(unique)}')
"
```

**Alternative — weight by domain distinctness:**
A failure that recurs 30 times is ONE finding, not 30 findings. Coverage = covered_unique / unique_findings, not covered / raw_count.

**Recommendation:** Fix the `self-regression.py` script to dedup by (source, question_stem) before reporting coverage. Without this fix, coverage % will never exceed ~15% on the current corpus shape.

---

## 3. Policy Store Saturation — Provisional Policies That Never Fire

**Pattern:** A correction creates a policy with `status: provisional`, `confidence: 0.3`, `hits: 0`. The enforcer only reads `status: active` policies at action time. So provisional policies can never accumulate hits and never get promoted. They sit in the store forever, contributing to trend-analyzer "persistently untriggered" noise.

**Real-world example (2026-06-19):**
- 8/10 policies have `hits: 0` after 36+ near-miss cycles
- Trend analyzer flags 9 policies as persistently untriggered
- But the enforcer reads them as documentation only

**Fix — one of:**

(a) **Wire provisional policies into the enforcer's read path** with a lower trigger threshold. Provisional = "warn + log"; active = "block + log". This gives them a chance to hit and prove value.

(b) **Auto-demote after 7 days at `hits: 0`** — already in the meta-improver spec, but check it's actually firing. Run `otto-learn review` weekly; demote anything at 0 hits after a week.

(c) **Trust the trend analyzer** — its `persistently_untriggered_policies` list is the demote queue. Don't wait for a manual review.

**Recommended:** (b) + (c). Auto-demote handles the bulk; trend analyzer surfaces exceptions.

---

## 4. Cron `Script:` Field Pitfall — Inline Content vs File Path

**Pattern:** When creating a cron job, the `Script:` field is the **filename** relative to `~/.hermes/scripts/`, NOT the script's content. Inline `#!` content gets stored as a literal path string, producing "Script not found" errors.

**Real-world example (2026-06-19):**
- `ca7dde96adcf` (weekly lux verify) was created with the script content inline
- Field shows: `Script: #!/bin/bash\n# Weekly lux verify across...`
- Hermes treats this as a relative path → file not found → silent no-op
- The job has never fired

**Fix:**
```bash
# WRONG
hermes cron add "weekly-verify" "0 0 * * 0" "#!/bin/bash\ncd ~/code..."

# CORRECT
echo '#!/bin/bash
cd ~/Documents/code/lux
npm run lux -- spec verify 2>&1 | tail -5' > ~/.hermes/scripts/weekly-lux-verify.sh
chmod +x ~/.hermes/scripts/weekly-lux-verify.sh
hermes cron add "weekly-verify" "0 0 * * 0" "weekly-lux-verify.sh"
```

**Detection:** Run `hermes cron list` and grep for `Script:` lines starting with `#!`. Any matches are broken jobs.

---

## 5. Reflection File Repetition — Hook Echoes Same Content

**Pattern:** The post-correction reflection hook fires periodically but writes the same boilerplate each cycle. The daily reflection file becomes a wall of identical "Auto-Reflection — HH:MM" entries. The hook is "running" but producing no signal.

**Real-world example (2026-06-19):**
- `~/.hermes/logs/reflection/2026-06-19.md` has 13 identical "Auto-Reflection" entries from 00:04 to 06:58
- Each one has the same firings list (5 entries, all `pol-20260618-007`)
- "Policies in store: 10" in every entry — no change recorded

**Fixes:**

(a) **Make the hook skip when nothing changed** — only append when a new correction actually fired or when firings actually changed:
```python
# In reflect-on-correction.py
current_state = json.dumps({"firings": recent_firings, "policies": policy_count})
if current_state == last_appended_state:
    return  # silent — nothing to record
```

(b) **Hash the firings list and only append on hash change.** The "Auto-Reflection — HH:MM" entry should only appear when a real event happened at that time.

(c) **Replace the boilerplate template with a delta log.** Each entry records only what changed since the last entry: "pol-20260618-007 fired 2x", "policy 003 demoted", etc.

**Recommended:** (a) — simplest, lowest risk.

---

## 6. Watchdog Restart-Loop Exit Code 2

**Pattern:** The watchdog script exits with code 2 + stdout "🔁 RESTART LOOP: gateway not sustained-alive over last 3 runs" when it detects the daemon has restarted >3 times. Exit code 2 is interpreted by cron as an error. The watchdog's own healthy alert becomes a noisy failure in cron logs.

**Fix — distinguish "I detected a problem" from "I failed to run":**
- Exit 0 with stdout: detected-and-resolved or detected-and-pending
- Exit 1: probe infrastructure failure (can't read state, script crashed)
- Exit 2: **don't use this for "I found an issue"** — reserve it for "the watchdog itself failed"

Stdout content with a fingerprint already drives the alert system. Exit code 2 in cron logs is misleading.

---

## Diagnostic Checklist — Run Before Declaring "Everything Fine"

When the daily audit shows "0 alerts" or "all green", verify before reporting:

1. **Watchdog freshness:** last summary timestamp within the past 30 min? If older, watchdog itself is stalled.
2. **Cron freshness:** all `Last run` timestamps within their schedule period? (cron with `every 15m` should have last-run ≤ 20m ago)
3. **Open fingerprint count vs raw open count:** summary's `open_fingerprints` should be ≤ 5. If raw count is much higher, the resolution loop pitfall (§1) is firing.
4. **Coverage corpus size:** if >50 entries but coverage <20%, run dedup (§2) before trusting the % number.
5. **Policy store size:** if >15 policies with `hits:0`, run demote queue (§3) before reporting "10 active policies".
6. **Reflection file growth:** if today's reflection is >2x yesterday's size with no real corrections, the echo pitfall (§5) is firing.

If any of these fail, the audit is producing misleading output. Fix the audit substrate first, then re-run.

---

## Quick Wins (Run These In Order)

```bash
# 1. Detect broken cron script fields
hermes cron list 2>&1 | grep -E "Script:.*#\!|Script:.*shebang" | head

# 2. Demote dead policies
otto-learn review  # shows candidates
otto-learn demote <id1> <id2> ...

# 3. Detect reflection echo
wc -l ~/.hermes/logs/reflection/$(date +%Y-%m-%d).md
# If >100 lines with identical structure, the hook is echoing.

# 4. Dedup regression corpus
python3 -c "..."  # see §2 above

# 5. Check raw vs summary open fingerprints
tail -1 ~/.hermes/logs/alerts/watchdog.jsonl | python3 -m json.tool | grep open_fingerprints
grep -c '"status": "open"' ~/.hermes/logs/alerts/watchdog.jsonl
# If raw >> summary, §1 is firing.
```
