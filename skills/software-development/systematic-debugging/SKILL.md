---
name: systematic-debugging
description: "4-phase root cause debugging: understand bugs before fixing."
version: 1.2.0
author: Hermes Agent (adapted from obra/superpowers)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [debugging, troubleshooting, problem-solving, root-cause, investigation]
    related_skills: [test-driven-development, plan, subagent-driven-development]
---

# Systematic Debugging

## Overview

Random fixes waste time and create new bugs. Quick patches mask underlying issues.

**Core principle:** ALWAYS find root cause before attempting fixes. Symptom fixes are failure.

**Violating the letter of this process is violating the spirit of debugging.**

## The Iron Law

```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```

If you haven't completed Phase 1, you cannot propose fixes.

## When to Use

Use for ANY technical issue:
- Test failures
- Bugs in production
- Unexpected behavior
- Performance problems
- Build failures
- Integration issues

**Use this ESPECIALLY when:**
- Under time pressure (emergencies make guessing tempting)
- "Just one quick fix" seems obvious
- You've already tried multiple fixes
- Previous fix didn't work
- You don't fully understand the issue

**Don't skip when:**
- Issue seems simple (simple bugs have root causes too)
- You're in a hurry (rushing guarantees rework)
- Someone wants it fixed NOW (systematic is faster than thrashing)

## The Four Phases

You MUST complete each phase before proceeding to the next.

---

## Phase 1: Root Cause Investigation

**BEFORE attempting ANY fix:**

### 1. Read Error Messages Carefully

- Don't skip past errors or warnings
- They often contain the exact solution
- Read stack traces completely
- Note line numbers, file paths, error codes

**Action:** Use `read_file` on the relevant source files. Use `search_files` to find the error string in the codebase.

### 2. Reproduce Consistently

- Can you trigger it reliably?
- What are the exact steps?
- Does it happen every time?
- If not reproducible → gather more data, don't guess

**Action:** Use the `terminal` tool to run the failing test or trigger the bug:

```bash
# Run specific failing test
pytest tests/test_module.py::test_name -v

# Run with verbose output
pytest tests/test_module.py -v --tb=long
```

### 3. Check Recent Changes

- What changed that could cause this?
- Git diff, recent commits
- New dependencies, config changes

**Action:**

```bash
# Recent commits
git log --oneline -10

# Uncommitted changes
git diff

# Changes in specific file
git log -p --follow src/problematic_file.py | head -100
```

### 4. Gather Evidence in Multi-Component Systems

**WHEN system has multiple components (API → service → database, CI → build → deploy):**

**BEFORE proposing fixes, add diagnostic instrumentation:**

For EACH component boundary:
- Log what data enters the component
- Log what data exits the component
- Verify environment/config propagation
- Check state at each layer

Run once to gather evidence showing WHERE it breaks.
THEN analyze evidence to identify the failing component.
THEN investigate that specific component.

### 5. Trace Data Flow

**WHEN error is deep in the call stack:**

- Where does the bad value originate?
- What called this function with the bad value?
- Keep tracing upstream until you find the source
- Fix at the source, not at the symptom

**Action:** Use `search_files` to trace references:

```python
# Find where the function is called
search_files("function_name(", path="src/", file_glob="*.py")

# Find where the variable is set
search_files("variable_name\\s*=", path="src/", file_glob="*.py")
```

### 6. Verify the Supervised Program is the One You Think It Is (NEW 2026-06-18)

**When the bug report is "X keeps dying/restarting/looping"**, the single highest-leverage Phase 1 check is to verify that the supervisor (cron, watchdog, orchestrator) is actually supervising the program the report says it's supervising. This is a distinct failure class from crashes, hangs, or OOMs — call it **supervisor-target mismatch**.

**Symptoms that suggest supervisor-target mismatch (vs. a real crash):**
- A watchdog restarts the process on a precise schedule (e.g., every 5 min like clockwork)
- The process exits "cleanly" (exit code 0) between restarts
- Log signatures in the failing process do NOT appear in the source files of the program the supervisor claims to be running
- The pattern persists across watchdog fixes (longer backoff, stderr capture, etc.) — the watchdog is fine; the target is wrong
- Running the program directly (bypassing the supervisor) succeeds for hours

**The 4-step verification:**

```bash
# 1. What does the supervisor's launch line actually invoke?
cat /path/to/watchdog.sh
# Read the binary, the entry-point function, the --module, the script name

# 2. What's the actual long-lived program in the project?
grep -A1 "\[project.scripts\]" pyproject.toml        # Python
grep -A1 '"scripts"' package.json                     # Node
grep -A1 '^\[bin' Cargo.toml                          # Rust

# 3. Do the two match? Compare exact strings.
# Common gotchas:
#   - hyphen vs underscore: "signal-engine" vs "signal_engine"
#   - one-shot vs loop: run_e2e() vs main() with while True
#   - module path: python -m foo.bar vs python -c "from foo.bar import main; main()"
#   - script wrapper: ./bin/foo vs .venv/bin/foo (different shebangs)

# 4. Run the actual long-lived program yourself, with the same logging
#    discipline the supervisor should be using. If it stays up for >> the
#    watchdog's restart interval, the supervisor is the bug.
```

**Real-world example (this skill's origin case, 2026-06-18):**

> Symptom: signal-engine-daemon-watchdog fires every 5 min, "Started PID N"
> Phase 1 hypothesis: daemon is crashing in feature extraction
> Phase 1 actual root cause: watchdog was launching `signal-engine-run` (a one-shot `run_e2e` batch job that exits when done), not the real looping `signal_engine.daemon`. The watchdog's `pgrep -f "signal-engine"` (hyphen) didn't match the real daemon `signal_engine.daemon` (underscore) — so it never saw the real daemon was fine. Direct run of `python -m signal_engine.daemon` lived for 16+ minutes with no crash.

**The 30-second shortcut:** when "X keeps dying" is the report, do the supervisor-target check FIRST. It takes 4 commands. If the supervisor is supervising the wrong program, every other Phase 1 hypothesis is a distraction.

**This goes in the same family as "the symptom isn't the bug."** Don't fix the watchdog, fix the entry point.

### 7. "Registered but never ran" — single-malformed-entry-poisons-loop (NEW 2026-08-04)

**When the bug report is "this cron/scheduler job exists but has `last_run_at: null` / has never fired"**, the single highest-leverage Phase 1 check is to invoke `get_due_jobs()` (or the equivalent due-job iterator) directly and capture its error output. The job may never run because one malformed entry in the shared iteration crashes the entire dispatch loop — and that crash is usually silenced by the surrounding `try/except` in the tick driver.

**Symptoms that suggest single-entry-poisons-loop (vs. a scheduler is down):**
- One specific registered job shows `last_run_at: null` while sibling jobs from the same era have `last_run_at` populated
- The job has a bare-minimum schema (missing `next_run_at`, `last_run_at`, `repeat`, `last_status`) — typical when registered via direct `jq` write or a tool that bypassed the schema-normalizing `add_job()` path
- Other unrelated jobs also appear "stuck" because they were registered the same way and have the same schema defect
- `ps aux` shows the scheduler/ticker is alive (gateway thread, daemon, etc.) and ticking regularly
- The scheduler tick wraps `_get_due_jobs_locked()` (or equivalent) in a try/except that logs `cron tick error: %s` at DEBUG level — invisible without log-level change

**The 4-step verification:**

```bash
# 1. Confirm the scheduler is alive and ticking
ps -ef | grep -E "scheduler|gateway" | grep -v grep
# (No `cron/scheduler.py` daemon? The ticker may live inside the gateway process.
#  Check gateway/run.py for _start_cron_ticker → cron_tick() loop.)

# 2. Read the actual job entry from jobs.json (or equivalent config)
jq '.jobs[] | select(.id=="<broken-job-id>")' ~/.hermes/cron/jobs.json
# Compare against a working sibling job — bare-minimum schema is the tell.

# 3. Invoke get_due_jobs() / due-iterator directly with the runtime's python
<runtime-venv>/bin/python -c "from cron.jobs import get_due_jobs; print(get_due_jobs())"
# Use the runtime the scheduler ACTUALLY uses (often a venv), not system python.
# Capture the AttributeError or TypeError that the tick driver's try/except swallows.

# 4. Identify the malformed entry and the iteration order
# Common crash signatures in due-job iterators:
#   - schedule.get("kind")       → AttributeError when schedule is a bare string
#   - next_run_at datetime.parse → TypeError when next_run_at is None and recovery branch
#                                  hits another schema defect
# Iterate jobs in registered order; the crash aborts iteration BEFORE the loop
# reaches your job.
```

**Real-world example (2026-08-04):**

> Symptom: `self-improve-hourly` cron registered 2026-08-03, `last_run_at: null`, never fired.
> Phase 1 hypothesis: cron scheduler is down.
> Phase 1 actual root cause: Two other jobs (`otto-daily-digest`, `otto-db-cleanup`) had been registered with `schedule` as a bare string (`"0 9 * * *"`) instead of the proper `{kind, expr, display}` dict. When `cron/jobs.py:_get_due_jobs_locked()` walked the jobs list and reached one of these jobs first, line 1087 called `schedule.get("kind")` — `AttributeError: 'str' object has no attribute 'get'` — and the entire function aborted before reaching `self-improve-hourly`. The gateway's `_start_cron_ticker` swallowed the exception via `except Exception as e: logger.debug("Cron tick error: %s", e)`. No job was ever returned as due.
>
> Why other jobs worked: jobs that already had `next_run_at` populated skipped the recovery branch (`if not next_run:` at line 1085), so the crash on the str-schedule jobs only poisoned the loop for jobs that NEEDED recovery.

**The 30-second shortcut:** when "registered but never ran" is the report, do the direct-invoke check FIRST. The dispatch loop's crash is usually silenced by the surrounding tick driver's `try/except`. Don't fix the missing `next_run_at` — find the malformed entry that's crashing iteration BEFORE your job.

**Two-part substrate fix:**
1. **Defensive normalization at the iterator entry point** — coerce bare-string schedules to dict form, wrap the recovery branch in try/except so one bad job logs and skips instead of aborting
2. **Schema validation at registration** — bare-minimum JSON writes (e.g. via `jq` or shell) should be rejected or normalized before they hit the scheduler. Don't trust `jobs.json` shape; trust `add_job()`.

**This is in the same family as "supervisor-target mismatch":** the symptom is "job X didn't run," but the cause isn't X — it's some OTHER entry in the shared iterator that aborted the loop. Fix the iterator, not X.

### Phase 1 Completion Checklist

- [ ] Error messages fully read and understood
- [ ] Issue reproduced consistently
- [ ] Recent changes identified and reviewed
- [ ] Evidence gathered (logs, state, data flow)
- [ ] Problem isolated to specific component/code
- [ ] Root cause hypothesis formed

**STOP:** Do not proceed to Phase 2 until you understand WHY it's happening.

---

## Phase 2: Pattern Analysis

**Find the pattern before fixing:**

### 1. Find Working Examples

- Locate similar working code in the same codebase
- What works that's similar to what's broken?

**Action:** Use `search_files` to find comparable patterns:

```python
search_files("similar_pattern", path="src/", file_glob="*.py")
```

### 2. Compare Against References

- If implementing a pattern, read the reference implementation COMPLETELY
- Don't skim — read every line
- Understand the pattern fully before applying

### 3. Identify Differences

- What's different between working and broken?
- List every difference, however small
- Don't assume "that can't matter"

### 4. Understand Dependencies

- What other components does this need?
- What settings, config, environment?
- What assumptions does it make?

---

## Phase 3: Hypothesis and Testing

**Scientific method:**

### 1. Form a Single Hypothesis

- State clearly: "I think X is the root cause because Y"
- Write it down
- Be specific, not vague

### 2. Test Minimally

- Make the SMALLEST possible change to test the hypothesis
- One variable at a time
- Don't fix multiple things at once

### 3. Verify Before Continuing

- Did it work? → Phase 4
- Didn't work? → Form NEW hypothesis
- DON'T add more fixes on top

### 4. When You Don't Know

- Say "I don't understand X"
- Don't pretend to know
- Ask the user for help
- Research more

---

## Phase 4: Implementation

**Fix the root cause, not the symptom:**

### 1. Create Failing Test Case

- Simplest possible reproduction
- Automated test if possible
- MUST have before fixing
- Use the `test-driven-development` skill

### 2. Implement Single Fix

- Address the root cause identified
- ONE change at a time
- No "while I'm here" improvements
- No bundled refactoring

### 3. Verify Fix

```bash
# Run the specific regression test
pytest tests/test_module.py::test_regression -v

# Run full suite — no regressions
pytest tests/ -q
```

### 4. If Fix Doesn't Work — The Rule of Three

- **STOP.**
- Count: How many fixes have you tried?
- If < 3: Return to Phase 1, re-analyze with new information
- **If ≥ 3: STOP and question the architecture (step 5 below)**
- DON'T attempt Fix #4 without architectural discussion

### 5. If 3+ Fixes Failed: Question Architecture

**Pattern indicating an architectural problem:**
- Each fix reveals new shared state/coupling in a different place
- Fixes require "massive refactoring" to implement
- Each fix creates new symptoms elsewhere

**STOP and question fundamentals:**
- Is this pattern fundamentally sound?
- Are we "sticking with it through sheer inertia"?
- Should we refactor the architecture vs. continue fixing symptoms?

**Discuss with the user before attempting more fixes.**

This is NOT a failed hypothesis — this is a wrong architecture.

---

## Red Flags — STOP and Follow Process

If you catch yourself thinking:
- "Quick fix for now, investigate later"
- "Just try changing X and see if it works"
- "Add multiple changes, run tests"
- "Skip the test, I'll manually verify"
- "It's probably X, let me fix that"
- "I don't fully understand but this might work"
- "Pattern says X but I'll adapt it differently"
- "Here are the main problems: [lists fixes without investigation]"
- Proposing solutions before tracing data flow
- **"One more fix attempt" (when already tried 2+)**
- **Each fix reveals a new problem in a different place**

**ALL of these mean: STOP. Return to Phase 1.**

**If 3+ fixes failed:** Question the architecture (Phase 4 step 5).

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "Issue is simple, don't need process" | Simple issues have root causes too. Process is fast for simple bugs. |
| "Emergency, no time for process" | Systematic debugging is FASTER than guess-and-check thrashing. |
| "Just try this first, then investigate" | First fix sets the pattern. Do it right from the start. |
| "I'll write test after confirming fix works" | Untested fixes don't stick. Test first proves it. |
| "Multiple fixes at once saves time" | Can't isolate what worked. Causes new bugs. |
| "Reference too long, I'll adapt the pattern" | Partial understanding guarantees bugs. Read it completely. |
| "I see the problem, let me fix it" | Seeing symptoms ≠ understanding root cause. |
| "One more fix attempt" (after 2+ failures) | 3+ failures = architectural problem. Question the pattern, don't fix again. |

## Quick Reference

| Phase | Key Activities | Success Criteria |
|-------|---------------|------------------|
| **1. Root Cause** | Read errors, reproduce, check changes, gather evidence, trace data flow | Understand WHAT and WHY |
| **2. Pattern** | Find working examples, compare, identify differences | Know what's different |
| **3. Hypothesis** | Form theory, test minimally, one variable at a time | Confirmed or new hypothesis |
| **4. Implementation** | Create regression test, fix root cause, verify | Bug resolved, all tests pass |

### Performance (Slow Test Suite) Variant

For slow-test problems, the root cause is usually structural (one test doing a full end-to-end integration), not a code bug. Follow the variant in `references/slow-test-suite-optimization.md` instead of the standard flow — the "fix" is isolation and parallelization, not a code change.

## Hermes Agent Integration

### Investigation Tools

Use these Hermes tools during Phase 1:

- **`search_files`** — Find error strings, trace function calls, locate patterns
- **`read_file`** — Read source code with line numbers for precise analysis
- **`terminal`** — Run tests, check git history, reproduce bugs
- **`web_search`/`web_extract`** — Research error messages, library docs

### With delegate_task

For complex multi-component debugging, dispatch investigation subagents:

```python
delegate_task(
    goal="Investigate why [specific test/behavior] fails",
    context="""
    Follow systematic-debugging skill:
    1. Read the error message carefully
    2. Reproduce the issue
    3. Trace the data flow to find root cause
    4. Report findings — do NOT fix yet

    Error: [paste full error]
    File: [path to failing code]
    Test command: [exact command]
    """,
    toolsets=['terminal', 'file']
)
```

### With test-driven-development

When fixing bugs:
1. Write a test that reproduces the bug (RED)
2. Debug systematically to find root cause
3. Fix the root cause (GREEN)
4. The test proves the fix and prevents regression

## Real-World Impact

From debugging sessions:
- Systematic approach: 15-30 minutes to fix
- Random fixes approach: 2-3 hours of thrashing
- First-time fix rate: 95% vs 40%
- New bugs introduced: Near zero vs common

**No shortcuts. No guessing. Systematic always wins.**
