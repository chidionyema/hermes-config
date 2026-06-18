# Session 2026-06-18 — Relay Rollout (balls 17–21)

Companion to `references/session-2026-06-18-17-balls.md`. This file documents the **substrate rollout** that closed the loop on the earlier session's dropped balls, plus the four new balls (17–21) the rollout itself generated.

## What shipped (verified, not claimed)

The audit Claude (Opus 4.8, tmux session `otto-claude`, persistent consult channel) built and proved the relay substrate end-to-end. Build Claude (`otto-build`, parallel session, non-overlapping items) shipped the cron root-causes, alert-resolver rewrite, watchdog grading, and synthetic closed-loop proof on a second Claude.

| Substrate file | Purpose | Probe / receipt |
|---|---|---|
| `~/.hermes/queue/incoming/` | Cron alerts land here, never raw to user | Live: 4 open → 0 converged |
| `~/.hermes/scripts/hermes_fingerprint.py` | Canonicalize PID/timestamp-varying messages to one fingerprint | self-test PASS |
| `~/.hermes/scripts/hermes_queue.py` | submit / drain / status, atomic, dedup; new verb `resolve --fingerprint` for probe-verified clear | live: 4 → 0 |
| `~/.hermes/scripts/queue-curate.sh` | Drains queue → writes `pending-digest.json`, silent stdout | `queue-probe.sh` 6/6 PASS (after catching heredoc/stdin bug live) |
| `~/.hermes/scripts/otto-dispatch.py` + `.sh` | Reads digest, auto-remediates mechanical issues, forwards to user only what Otto decides matters | `otto-dispatch-probe.sh` 6/6 PASS |
| `~/.hermes/scripts/hermes_claims.py` | Dropped-ball watchdog: success claim only with a probe, escalates unverified | closed-loop-proof.sh 3/3 green |
| `~/.hermes/scripts/closed-loop-proof.sh` | Synthetic proof: inject fault → watchdog exit 2 → queue receives event → clear → resolve exit 0; also dropped-ball loop | PASS after self-fix (queue drain path was wrong) |
| `~/.hermes/scripts/watchdog-probe.sh` | watchdog.py exit-code grading: 4 cases including restart-loop escalation | 4/4 PASS after test C was fixed (self-healer auto-cleared the test alert) |
| `~/.hermes/scripts/watchdog.py` | Rewritten: grades on real invariants (daemon up N min, alert open K runs, daemon down → exit 2) | All probes green |
| `~/.hermes/scripts/alert-resolver.py` | Rewritten: probe-verified resolution, never message-absence. The 804/239 false-clear engine | `alert-resolver-probe.sh` PASS |
| `~/.hermes/scripts/signal-engine-daemon-watchdog.sh` | Fixed: launches `python -m signal_engine.daemon`, pgrep matches underscore variant, `PYTHONUNBUFFERED=1`, split stderr to `daemon.out.log`/`daemon.err.log`, unset `VIRTUAL_ENV` | `signal-engine-watchdog-probe.sh` (a)(b)(c) PASS |
| `~/.hermes/config.yaml:348-349` + `config.py:1757-1758` + `memory_tool.py:124` | Cap-raise: user 1375→2750, memory 2200→3300 (3 sources of truth) | `memory-capacity-probe` PASS — USER 47%, MEMORY 59% |
| `~/.hermes/cron/jobs.json` | `queue-curator` (`cca2c5482680`) drains every 5 min; **`otto-dispatch` (`f0b2079864c5`)** is the sole `deliver: origin` relay step; signal-engine-daemon-watchdog, health-watchdog, repo-health-check all switched to `deliver: local` | Live: user received a single triaged digest (7 issues) instead of 7 raw alerts |
| `~/.hermes/tests/` | pytest suite for hermes_fingerprint, hermes_queue, watchdog, dropped-ball watchdog, dispatcher, memory | First test suite in the estate |

## The 4 new balls (17–21) the rollout itself generated

These are the dropped balls the audit-and-fix process produced, captured so the next session doesn't repeat them.

### Ball 17 — relay topology gap + memory cap (closed by audit Claude)
- **Symptom:** user's cron output for `queue-curator` showed 2–3 memory-capacity warnings + 1 idle-continuous-learning warning on Telegram raw.
- **Root cause:** `queue-curate.sh` printed the digest to stdout, and `cca2c5482680` had `deliver: origin` → the digest bypassed Otto-as-dispatcher. Topology was `cron → queue → curator → user`. It is now `cron → queue → curator → OTTO → user`.
- **Otto's failure mode:** claimed "memory saved" after a memory write that silently failed (user_char_limit 1375, the file was at 1342). Read-back would have caught it. Lesson lives in the skill's Verification Protocol section.

### Ball 18 — Otto almost applied the jobs.json handback (closed by build Claude)
- **Symptom:** the audit Claude handed back two jobs.json changes; Otto started to apply them via the `cronjob` tool before Chidi caught it.
- **Root cause:** "Claude does the work end-to-end" rule was clear in the skill, but "Otto does NOT apply Claude's handbacks" wasn't. Otto treated Claude's handback as Otto's own cron creation.
- **Fix:** the rule is now explicit in both `claude-code` (Steering discipline) and `dropped-ball-prevention` (anti-patterns table). Build Claude applied the handbacks itself.

### Ball 19 — proving-ground-audit reports MISSING as warnings
- **Symptom:** `proving-ground-audit` (3c5a966ee24e) failed with: `popdd-ts/tests: NOT_FOUND, popdd-ts/build: NOT_FOUND, lux-popdd/tests: NOT_FOUND, lux-spec/tests: NOT_FOUND`.
- **Root cause:** the audit grades itself against missing files. Same class as the alert-resolver false-clear bug — auditor reports "ok" on broken things. Build Claude is in flight on this; the fix is to require explicit "not-required" markers for missing paths and exit non-zero on any missing required path.

### Ball 20 — real signal_engine.daemon died (the production daemon, not the repro)
- **Symptom:** `signal-engine-daemon-watchdog` fired again after the relay was live: "Signal Engine daemon not running. Restarting... Started PID 1228". The watchdog was launching the right entry point now; the daemon itself was dying on its own.
- **Root cause:** the stderr split (which Claude built in Fire 1) caught the real traceback: `FileNotFoundError: config.yaml not found at .../signalengine/config.yaml`. The repro daemon I ran in foreground worked because my cwd was the project root; the cron-launched daemon had a different cwd and no config. config.yaml now present. PID 1228 cycling cleanly ("Cycle complete. Equity: $9881.48").

### Ball 21 — relay still emitted one raw digest before the deliver=local change applied
- **Symptom:** first cron tick after the handback, the queue-curator cron still had `deliver: origin` for a few minutes, so the user got a raw triaged digest.
- **Root cause:** the `deliver: origin → local` change was a jobs.json handback that had to be applied; until applied, the cron still had its old delivery target. This is a one-tick transition, not a structural defect.
- **Lesson:** jobs.json handback latency is itself a dropped ball. The fix (build Claude is doing it): a single `apply-handback.sh` script Claude runs that applies ALL pending handbacks atomically, so Otto never has to apply any of them.

## Closed-loop proof transcript (abbreviated)

```
build Claude: bash scripts/closed-loop-proof.sh
OK   fault injected -> watchdog caught it (exit 2)
OK   relay queue RECEIVED the event (0 -> 1)
OK   condition cleared -> loop resolved (exit 0)
OK   dropped ball -> tracker caught it (exit 2)
OK   queue received dropped-ball aggregate
OK   tracker reached the queue
VERDICT: PASS — loop is closed
```

## Patterns that emerged this session (worth lifting to the umbrella)

1. **Build-time self-healers are themselves dropped balls.** Build Claude's test C initially used a `CRON_ERROR` that the production self-healer auto-cleared between runs, so the test was lying. Fix: tests must use conditions no self-healer can erase (e.g., `DISK_HIGH` with 0% threshold). This is a meta-rule: **a test that grades itself against a real signal the production system can mutate is itself a false-pass.**

2. **The stdin/heredoc trap.** Build Claude piped `status` output into `python3` while feeding the program via heredoc — the stdin got consumed by `status`, the heredoc read empty stdin, the digest came out empty. The probe missed this until the user pasted a real warning. Fix: probes now assert the digest contains the open item, not just that the curator ran silent.

3. **Two Claudes > one Claude only with non-overlap discipline.** Spin up `otto-build` for the non-keystone items, hand it the explicit partition (do not touch item 1, do not preempt the keystone, items 2-10 are yours). Brief it with the full context dump so it doesn't redo work. The two-session pattern in `claude-code` skill's "Multi-Session Coordination" section is the contract.

4. **Stream-by-stream handback beats batch handback.** The user said "who's so slow" after one Claude took 9 minutes on a single cron fix. Fix: Claude hands back each fix the moment its probe is green, doesn't wait for the consolidated handback. Otto applies nothing; Claude applies its own handbacks (Ball 18 lesson).

## Files in this skill's references/ that this companion depends on

- `references/session-2026-06-18-16-dropped-balls.md` — earlier snapshot
- `references/session-2026-06-18-17-balls.md` — full 17-ball transcript
- `references/session-2026-06-18-relay-rollout.md` — this file
- `scripts/probe-template.sh` — copy-paste starter for any new probe
