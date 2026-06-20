# Notification Quality — the user-facing gate

User demand (2026-06-19 session, corrected twice): every cron alert that reaches
the user MUST answer three questions:
  1. **WHAT** is wrong (the actual condition, not a generic escalation reason)
  2. **WHERE** it is (file, repo, system, fingerprint)
  3. **WHAT TO DO** (or "self-healed, not shown" if Otto handled it)

Anything that fails this gate is **cryptic** and constitutes a dropped ball.

## Root cause that produced `<N>` placeholders in delivered text

`hermes_fingerprint.py` deliberately replaces all numbers with `<N>` so recurring
conditions collapse to one stable fingerprint:

```python
_RE_NUM = re.compile(r"\b\d+\b")
# ...
s = _RE_NUM.sub("<N>", s)
```

This is correct for **dedup keys**. It is WRONG when the fingerprint is then
displayed to the user as a message. The actual `sample` (the real human-readable
text) lives in `queue/state.json` per-fingerprint and must be loaded separately
and used as the user-facing text.

## Fix — `otto-dispatch.py` user-facing block

1. **Load samples**: `_load_samples()` reads `state.json` for `fingerprint -> sample`.
2. **Group by source**: each `source` (repo-health, health-watchdog, etc.) becomes
   a section with a severity emoji and a count.
3. **Show sample, not fingerprint**: each line is `<emoji> — <sample>` where
   `sample` has the real numbers, paths, and PIDs.
4. **Cap at 5 per source**: keep message bounded. "... and N more" line for the rest.
5. **Self-healed footer**: `✓ N self-healed, not shown` if Otto auto-remediated.

### Before / after (real output from the same input)

BEFORE (cryptic, dropped ball):
```
🧭 Otto triage — 5 issue(s) need you:
  [crit] x27  repo-health [repo-health] — crit could not self-heal
  [crit] x8   repo-health [repo-health] — crit could not self-heal
  [crit] x8   repo-health [repo-health] — crit could not self-heal
  [crit] x1   repo-health [repo-health] — crit could not self-heal
  [crit] x1   repo-health [repo-health] — crit could not self-heal
(12 issue(s) self-healed by Otto, not shown)
```

AFTER (answers WHAT/WHERE/WHAT-TO-DO):
```
🧭 Otto triage — 6 issue(s) across 2 source(s):

🔴 health-watchdog — 1 fingerprint(s), 1 total occurrence(s)
    🔴 — GATEWAY_RESTART_LOOP: gateway not sustained-alive over last 3 runs (window up=[True, True, False])

🔴 repo-health — 5 fingerprint(s), 45 total occurrence(s)
    🔴 — signalengine: TIMEOUT (> 90s)
    🔴 — signalengine: TIMEOUT (> 20s)
    🔴 — lux: TIMEOUT (> 20s)
    🔴 — repo-health-check timed out after 120s
    🔴 — lux: TIMEOUT (> 90s)
```

## Dedup hash must key on displayable content, not canonical fingerprint

`_deduped()` was keying on the raw fingerprint, which canonicalizes to
`<N>` placeholders — so different-but-equivalent conditions
(`TIMEOUT (> 90s)` vs `TIMEOUT (> 20s)`) collided and the dedup was
effectively blind to the real "what changed."

Fix: hash on `(source, severity, sample[:120])` tuples so the dedup reflects
what the user actually saw delivered.

## Cron-budget pattern (dispatcher must not time out)

`otto-dispatch.sh` was hitting the 120s cron cap and timing out. Per
`references/cron-budget-subprocess-pattern.md`: the dispatcher wraps
the main loop with a `DISPATCH_BUDGET_S=100` ceiling (under the 120s cap with
20s headroom), and bails cleanly with a `budget_exceeded` log entry on overrun.
The next tick picks up the rest. **The dispatcher must NEVER be the thing that
times out** — it is the user-facing pipeline.

## Test the dispatcher manually

```bash
rm -f ~/.hermes/queue/dispatch-dedup.json ~/.hermes/queue/pending-digest.json*
cd ~/.hermes && bash scripts/queue-curate.sh
python3 scripts/otto-dispatch.py
```

Run twice in a row — second run should be silent (deduped). The
`dispatch-log.jsonl` should show a `deduped` entry on the second run.
