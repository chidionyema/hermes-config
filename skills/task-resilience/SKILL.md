---
name: task-resilience
description: "Auto-recover interrupted tasks, dispatch parallel work without blocking the user, size subagents to stay interruptible, fix defects before disclosing them, and redline user-owned documents (CVs, bios, LinkedIn drafts) safely. Load when working on tasks that may be interrupted, when dispatching subagents, when a defect is found mid-task, or when editing personal documents where preserving the original matters. When the task is CV/bio/LinkedIn writing (not editing), also load external-audience-writing — that skill owns the audience translation rules; this skill owns the file-surgery mechanics."
version: 1.3.0
author: LUX Engine
license: MIT
metadata:
  hermes:
    tags: [resilience, recovery, persistence, reliability, parallelism, dispatch, redline, cv]
---

# Task Resilience — Auto-Recovery, Parallel Dispatch, Defect Discipline, Document Redlines

## What It Does

You NEVER have to re-prompt after an interruption. The agent ALWAYS picks up where it left off.

It also enforces:

1. **Interruptible parallelism** — subagents dispatched with wall-time budgets ≤30s, so the user can steer mid-batch. Two-wave pattern for ≥3 parallel tasks.
2. **Fix-before-disclose** — defects found in shipped work get fixed in the same change, not deferred. Honest disclosure of an unfixed bug is a cop-out when the fix is in scope.
3. **Dispatch-gate discipline** — before any clarify() call, the dispatch gate (`~/.hermes/scripts/dispatch_gate.py`) evaluates whether the question can be answered autonomously. If `DISPATCH_NOW`, execute without asking. If the same correction about asking-vs-doing fires twice, escalate to structural enforcement (dispatch gate rule), not another policy.
4. **Greenlight-before-spawn** on user-facing deliverables (CV bullets, READMEs, marketing) — scope agreement before drafting. NOTE: this applies only to documents for *external* audiences (CVs, public READMEs, marketing). For engineering work (code, tests, config, automation), default to ACT — the dispatch gate decides.
5. **Redline discipline** for user-owned documents — preserve the original, insert-only by default, write to a new file, anchor insertions by text not index.

## Loaded Companion Skills

- **`external-audience-writing`** — load this when the task is a CV, bio, LinkedIn, or any external-audience document. That skill owns the audience translation rules (translate brand names to industry terms, drop insufficient-evidence subsections, sprinkle AI/agentic content into the current role rather than top-level section). This skill owns the file-surgery mechanics.

## Reference Files

- `references/cv-and-document-redlines.md` — file-surgery recipe for `.docx`/`.pages`/`.pdf` (zip manipulation, XML editing, paragraph anchoring pitfalls, version discipline)
- `references/dispatch-discipline.md` — greenlight-before-spawn worked examples, the "I'll just note the bug" failure mode catalog, and the "should I ask for scope or dispatch?" quick checklist
- `references/hermes-config-backup.md` — what gets backed up, where, how to restore, auto-push setup
### Policy store reference (external)
Correction-learning loop: `otto-learn list` for all policies; `~/.hermes/policies/` for individual policy files; `~/.hermes/logs/policy-firings.jsonl` for firing history
### Dispatch gate script (external)
`~/.hermes/scripts/dispatch_gate.py` — pre-commit gate against asking permission. Run this before every clarify() call.

|## How It Works
|
|1. **Before every tool call**: Task state is saved to `~/.hermes/task-state/current_task.json`
|2. **If interrupted** (crash, timeout, system load): State persists on disk
|3. **On next session start**: Agent auto-detects interrupted task, reads resume prompt
|4. **Agent auto-resumes**: Continues from exactly where it stopped
|5. **On completion**: State is cleared
|
|### Recovery Loop (new in v1.3)
|
|When a task completes with non-success status, the **recovery loop** fires automatically:
|
|1. **Classify the failure**: `task_result.py` classifies output as transient/logic/blocked
|2. **Route to recovery**: `recovery_loop.py` executes the appropriate action
|3. **Return final result**: After all retries or re-dispatch
|
|```
|Task completes
|  ├── success → return result (no recovery)
|  ├── transient → retry with backoff: 2s, 5s, 15s (3 attempts max)
|  ├── logic → escalate to Claude strategist → re-dispatch with revised plan
|  └── blocked → surface to user with specific blocker description
|```
|
|### Async Job Queue (new in v1.3)
|
|Long tasks (>30s) can dispatch via the async job queue and return immediately:
|
|1. Create a `Job` with a goal and command
|2. Dispatch it as a background process (`terminal background=true`)
|3. Control returns to the conversation immediately
|4. Job state persists in `~/.hermes/task-queue/jobs.json`
|5. On completion, recovery loop fires if needed
|
|## Usage
|
|The agent handles this automatically. You don't need to do anything.
|
|## Structured Result Wrapper
|
|Every `delegate_task` call should be wrapped for structured results:
|
|```python
|from task_result import wrap_delegate_result, TaskResult
|
|# Wrap raw output into structured result
|result = wrap_delegate_result(raw_output, goal="Run tests")
|
|# Check status and error class
|if result.status != "success":
|    print(f"Error class: {result.error_class}")
|    print(f"Error: {result.error[:200]}")
|```
|
|## Recovery Dispatch
|
|For one-call dispatch with auto-recovery:
|
|```python
|from __init__ import safe_dispatch
|
|result = safe_dispatch(
|    dispatch_fn=lambda: my_task_function(),
|    goal="Run integration tests",
|    max_retries=3,
|)
|
|if result.is_success:
|    print("Task succeeded!")
|elif result.error_class == "blocked":
|    print("Blocked — surface to user:", result.error)
|```
|
|## Async Job Dispatch
|
|For long-running background tasks:
|
|```python
|from async_queue import create_job
|
|# Create and persist a job
|job = create_job(
|    goal="Run full test suite",
|    command="pytest tests/ -v",
|)
|job.dispatch()
|print(f"Job {job.id} running (session: {job.session_id})")
|# Control returns immediately — check status later
|```
|
|### Manual commands (for debugging)

## Default to Parallel — The "Heavenly Experience" Rule

The user is serial (one message at a time), but I am not. **Whenever I identify >=2 independent work items, dispatch them in the same tool-call batch using `delegate_task` (subagents) or `background=true, notify_on_complete=true` (processes).** Never make the user wait for one thing to finish before I start the next.

**Decision tree:**
- Independent CPU work → spawn subagents in parallel (delegate_task batch)
- Independent shell commands (e.g., git status + ls + test) → put them in the same function_calls block
- Long-running commands (>=30s) → background=true, work on the next thing, notification arrives
- The user asks "what's next" or "what's your menu" → that's a request for the **menu of all currently-actionable items**, not a status update on the one I'm doing. Surface the whole menu immediately, then keep working.

**Anti-pattern to avoid:** "I finished A. Now what?" — the right move is to dispatch A, B, C, D, E concurrently, then report when they all complete.

## Dispatch-Time Decision Rule (NEW — fire before every delegate_task)

Before dispatching any work, I decide: when this result comes back, do I:

- **ACT** — priority is clear, approach is clear, fix it immediately and report after
- **REPORT** — result is informational, surface it with context
- **SURFACE** — result has tradeoffs I can't resolve, needs user input

This decision is made at **dispatch time, not result time.** If I find myself freezing when a result lands, it's because I didn't decide upfront. The three reasons to surface (ask the user):
1. The task is blocked (needs a key, a decision, a resource)
2. The result contradicts what we expected (needs strategist review)
3. The approach has tradeoffs that genuinely can't be resolved from the spec

Everything else: ACT. Report after, not ask before.

## CRITICAL: Subagent Wall-Time Budget — Stay Interruptible

Subagents run **synchronously** inside my turn. If I dispatch a subagent with a 3-minute wall-time budget, **any user message that arrives during those 3 minutes is queued, not delivered to me.** The user cannot steer, cancel, or redirect that work without a hard `/stop` that kills everything.

This is the **blocking failure mode** the user has called out explicitly. The fix is structural, not cosmetic:

**Rule: never give a subagent a wall-time budget > 30 seconds unless the work is genuinely uninterruptible.**

- **≤30s subagent tasks** (file edits, single file reads, drafting a paragraph, running a small command) → safe to batch. The user can wait 30s and steer.
- **30s–2min subagent tasks** (writing a 200-line file, running a test, building a small project) → batch with 2-3 of these max, never more, and have them all finish before the next turn's user message could plausibly arrive.
- **>2min subagent tasks** (full integration test runs, large file generations, multi-file refactors) → **break into stages**. Each stage returns within 30s with a checkpoint the user can react to. The subagent works in slices, reports between slices, and re-checks the priority queue (the user message) before continuing.

**The check-between-stages pattern:**
```
# WRONG: one 5-minute subagent that runs uninterrupted
delegate_task(goal="Run full integration suite and produce report")

# RIGHT: staged subagent that reports every 30s
delegate_task(goal="Run first 5 test files. After each file, emit a one-line progress note. After file 5, STOP and report what passed/failed. Wait for further instructions before running files 6-10.")
```

**The interrupt window:** when I dispatch parallel work, I must leave an interrupt window — a gap between tool calls where user messages can be processed. If I'm about to dispatch 5 subagents, the first one starts a 30s timer, the others queue. The user message arrives in that 30s window, and the queued subagents I haven't dispatched yet can be cancelled. So: **stage the dispatch in two waves** (3 fast, then 2 slower), don't dump 5 in one tool-call block.

**When the user says "stop that" or "don't do that" while work is in flight:**
1. If a subagent is already running, I cannot stop it without `/stop` — but I can **not dispatch the queued ones**.
2. I acknowledge the steering immediately, mark the unstarted subagents as cancelled in the todo list, and adjust the in-flight subagent's work if it has a "stage 2" hook (which it should, per the rule above).
3. I report what I cancelled and what remains running.

**Practical sizing for this session:**
- Reading 1-3 files → safe inline
- Editing 1-2 files → safe inline
- Drafting a doc ≤200 lines → safe inline (fast)
- Drafting a doc >200 lines → subagent, 30-60s budget
- Running a test suite that finishes in ≤30s → inline
- Running a test suite >30s → background=true + notify_on_complete, or subagent with stage reporting
- A "do everything" multi-hour task → NEVER as a single subagent. Break into 5-10 stages, each ≤2min, with progress reports between.

## Don't Substitute "Honest Disclosure" For a Fix

When I find a defect while working, the default response is **fix it now**, not note it and move on. "Honest disclosure of an unfixed bug" is a cop-out if the fix is cheap and within scope. The receipts/signatures/proofs that POPDD produces are only valuable if they reflect *real* state. A signed receipt that says "0 passed, 0 failed" with a real test suite behind it is a **false attestation** — the opposite of what POPDD exists to prevent.

**The bar:** if a defect is in the work I'm shipping, fix it before declaring done. Disclose-then-defer is only acceptable when the fix would be its own ≥1-hour task and is genuinely out of scope.

## Pitfall: `execute_code` Blocks On User Consent, Not Just Runtime

If a script in `execute_code` exceeds the 5-minute timeout (or shows signs of hanging), the runtime returns a `BLOCKED: execute_code script timed out without user response` error. **This is not a fatal error you should retry around** — rephrasing the script won't help.

The right response when you see this error:
1. **Do NOT retry the same script** — it'll block again
2. **Convert the work to discrete `terminal()` calls** with explicit timeouts and progress checks
3. **Switch to `background=true, notify_on_complete=true`** for any task > 30 seconds
4. **Break the work into smaller pieces** that complete within the 5-min limit

This catches you especially when exploring large codebases with recursive `os.walk` — a recursive walk over a large tree can exceed 5 min. Use `search_files(target="files", path=...)` with a scoped pattern instead.

## Pitfall: Presenting Options When Priority Is Clear — The Permission Trap

The most common failure mode: I receive a clear, prioritised set of findings from a strategist/agent dispatch, and instead of acting on them I present them to the user as options: "Want me to dispatch these? Which one first?"

**This is wrong when the priority and approach are clear from the spec.** The user should never have to tell me to act on the top-priority item of a list *they asked me to create*. The triage was commissioned to produce an action plan — presenting that plan back for approval instead of executing it is cycle-wasting.

**The guard:** Before presenting findings to the user, ask:
- Is the next action unambiguous from the findings? → ACT, don't surface
- Is there a genuine tradeoff (cost, risk, sequencing) I can't resolve? → SURFACE with the tradeoff stated
- Am I waiting for permission because I'm uncertain? → That's my problem, not theirs. Escalate to strategist instead of user.

**Correction-learning loop:** When I get corrected on this, the lesson goes into the policy store at `~/.hermes/policies/`. Run `otto-learn add <trigger> <rule> --source <correction_text>` immediately.

**Structural enforcement (policy-enforcer resource classification — active):**
- `~/.hermes/scripts/policy-enforcer.py` — classifies every action by resource needs (auto_exec / needs_human / needs_clarification). Always returns PASS; never blocks. Zero question-form detection. Whitelist-based: adding a new capability adds an entry to `AUTO_EXECUTABLE_TOOLS`, not another English pattern.
- `~/.hermes/specs/policy-enforcer-redesign.md` — full design rationale
- `~/.hermes/scripts/reflect-on-correction.py` — post-correction hook: appends root-cause analysis to daily reflection, audits policies for promotion.
- When a correction fires: (1) write policy JSON, (2) update enforcer capability list if needed, (3) run reflection.

## Pitfall: Multi-Project State Spans Multiple Directories

When you're working across multiple sibling projects (e.g. `~/Documents/code/lux/`, `~/Documents/code/signalengine/`, `~/Documents/code/prospector/`), `task_state.py save` saves one description but the work spans many working directories. Don't use a single task state to track cross-project work — use a Todo list (`todo` tool) for the cross-project plan, and `task_state.py save` for the per-project checkpoint. Cross-reference the todo IDs in the task state description.

When switching between projects, **always re-state the working directory and the project name** in your first message after the switch. Future agents (and the user) reading the transcript need to know which project each tool call was operating on.

## When the User Interrupts

If the user sends a message while a long task is running, the right response is:

1. **Acknowledge the interruption** (don't ignore it)
2. **Check if the running task is still relevant** — if so, note it's still going (session_id)
3. **Process the new request in parallel** — start new work while the old task continues
4. **When the original task completes**, the notification will come in and you'll know

The "interrupting kills the work" feeling is what this skill is designed to prevent. **Tasks persist, state saves, you can have multiple things running at once.**
