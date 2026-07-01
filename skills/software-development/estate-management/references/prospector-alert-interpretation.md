# Prospector Alert Interpretation

What each diagnostic alert means, how severe it is, and what to do about it. Alerts appear at the end of each generation batch in `/tmp/prospector_gen.log`.

## Alert Reference

| Alert | Severity | Meaning | Action |
|-------|----------|---------|--------|
| `zero_yield` | 🚨 crit | 0 PASS across N ruled candidates in a lane. The gene pool for that lane is dead. | Investigate whether this reflects genuine selectivity (all ideas truly bad for that lane) or calibration regression (gates too strict, exploration too low). Check `quality_decay` — if both fire, the generator is producing low-value ideas that the moat is correctly rejecting. |
| `quality_decay` | 🚨 crit | Rolling alpha (avg score of PASSes) has dropped below threshold (typically < 3.0). Generator is producing lower-value ideas. | Check exploration levels (`adaptive.py`), recent failure mode feedback (kill patterns may be steering into dead zones), and whether kill patterns are narrowing the gene pool too aggressively. |
| `dead_gate` | ⚠️ warn | A configured gate has never fired. May be unreachable behind kill-fast (earlier gates kill before this one is reached). | Review gate ordering in `config.yaml`. If `value_durability` and `incumbency` kill everything, later gates (`legality`, `distribution`) never get exercised. Either reorder or accept that these gates are shadow guards. |
| `moat_exhausted` | ⚠️ warn | Moat operator chain depleted — candidates deferring. | Check Claude/Gemini API credits and circuit breaker health files. |

## Interpreting a 0% Survival Batch

When all candidates in a batch are KILLed, the diagnostic flow is:

1. **Check which gate fired most** — is it always `value_durability`? Always `incumbency`? This tells you where candidates are dying.
2. **Check confidence scores** — low conf (0.2–0.4) + KILL = the moat is uncertain but killing anyway (possible over-rejection). High conf (0.7+) + KILL = genuinely bad ideas.
3. **Check for `unverifiable` verdicts** — many `unverifiable` results mean retrieval failed (no web passages found), not that the idea is bad. The system forces `unverifiable` when no citations exist.
4. **Check `zero_yield` count** — if it spans 35+ candidates across multiple lanes (growth, venture, smb), it's likely a systemic issue, not a bad batch.
5. **Check `quality_decay` alpha** — if it's trending down over days, the generator's exploration is collapsing.

## Interpreting `dead_gate`

The gate order in `config.yaml` determines kill-fast behavior. The first gate to hard-fail stops the remaining checks. Common patterns:

| Dead Gate | Likely Killer | Diagnosis |
|-----------|---------------|-----------|
| `legality` | `value_durability` or `incumbency` | Ideas are dying on business-model grounds before legal checks run. This is fine — legality is a backstop. |
| `distribution` | `value_durability` | Ideas aren't reaching distribution feasibility checks. May indicate the gene pool is too narrow (all ideas share similar distribution channels that `value_durability` flags). |
| `payer_solvency` | `pain_reality` | Ideas are being killed for not solving a real problem. Payer solvency is moot if the problem doesn't exist. |

## Real Example: 2026-06-24 Batch

```
PASS 0 / KILL 3   survival 0%
🚨 [zero_yield] 0 PASS across 35 [growth] ruled candidates
🚨 [zero_yield] 0 PASS across 33 [venture] ruled candidates
🚨 [quality_decay] Rolling alpha dropped to 2.94
⚠️ [dead_gate] [growth] gates never fired: ['legality', 'pain_reality']
⚠️ [dead_gate] [venture] gates never fired: ['distribution', 'legality', 'payer_solvency']
```

**Interpretation:** `value_durability` and `incumbency` are the dominant killers (2/3 candidates killed by them). The gap between `dead_gate` on `pain_reality` (growth lane) vs its presence as the sole PASS for VanGuard Pay suggests the gate ordering creates a structural blind spot — `pain_reality` only runs for candidates that survive `value_durability` + `incumbency` + `payer_solvency` + `distribution` + `legality`, which almost none do.

**Recommendation:** Not a bug — the system is correctly rejecting ideas that fail the hardest gates first. But the `quality_decay` at 2.94 warrants checking whether kill feedback is steering generation into a collapsing funnel.
