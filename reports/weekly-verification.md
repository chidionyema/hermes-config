# Weekly lux verify — 2026-06-22

Triggered by failure task `CRON_STALE: Run lux verify on all projects with specs (not run in 26h)`.

## CRON_STALE verdict: FALSE POSITIVE — resolved

The cron job `ca7dde96adcf` is scheduled **weekly** (`0 0 * * 0`). It ran on time
**Sun 2026-06-21 00:00 BST** (`last_status: ok`) and is correctly scheduled next for
**2026-06-28**. "Not run in 26h" is expected Mon–Sat for a weekly job.

The alert came from the **old flat-elapsed** staleness heuristic. The current
`~/.hermes/scripts/watchdog.py` (lines 104–123) is already schedule-aware — it grades
against each job's `next_run_at`, not raw elapsed time. Live `check_cron_health()` over the
current `cron/jobs.json` emits **0 CRON_STALE alerts**; the lux verify job is not flagged.
Acceptance test (condition no longer reproduces): **PASS**.

## Spec verification run (per project)

| Project       | lux CLI variant            | Verify form that works                         | Result |
|---------------|----------------------------|------------------------------------------------|--------|
| lux (node)    | `npm run lux -- spec …`    | `spec verify <name>` / `spec guard <name>`     | OK     |
| signalengine  | `lux-spec spec {verify,guard,…}` | `lux-spec spec verify calculate_fee` → signed receipt | OK |
| prospector    | `lux-spec {verify,lint,info}` | **CLI verify unsupported** — "requires providing an implementation module; use the Python API" | BLOCKED |

## Secondary finding (separate ticket — NOT the CRON_STALE bug)

`scripts/weekly-lux-verify.sh` uses one hardcoded invocation
(`uv run lux-spec spec verify`) for all projects, but the three projects ship **three
different `lux-spec` CLIs** with incompatible argument shapes:

- signalengine needs a spec **name** (or `lux-spec spec guard` as a verify-all CI gate);
- prospector's CLI variant **cannot verify from the CLI at all** (needs the Python
  `luxspec.SpecVerifier` API);
- the node project needs `npm run lux -- spec guard/verify <name>`.

So the weekly script currently only really exercises LUX. The job still exits 0 (report
semantics), so it does **not** crash the cron — which is why this never surfaced as a
CRON_ERROR. Recommended fix (own ticket, low risk): per-project verify-all using
`spec guard` for node+signalengine and a small Python harness for prospector. Not fixed
here to avoid a wrong guess that would make the weekly report silently lie.
