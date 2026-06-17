---
name: plan
description: "Plan mode: write an actionable markdown plan to .hermes/plans/, no execution. Bite-sized tasks, exact paths, complete code."
version: 2.0.0
author: Hermes Agent (writing-craft adapted from obra/superpowers)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [planning, plan-mode, implementation, workflow, design, documentation]
    related_skills: [subagent-driven-development, test-driven-development, requesting-code-review]
---

# Plan Mode

Use this skill when the user wants a plan instead of execution.

## Core behavior

For this turn, you are planning only.

- Do not implement code.
- Do not edit project files except the plan markdown file.
- Do not run mutating terminal commands, commit, push, or perform external actions.
- You may inspect the repo or other context with read-only commands/tools when needed.
- Your deliverable is a markdown plan saved inside the active workspace under `.hermes/plans/`.

## Output requirements

Write a markdown plan that is concrete and actionable.

Include, when relevant:
- Goal
- Current context / assumptions
- Proposed approach
- Step-by-step plan
- Files likely to change
- Tests / validation
- Risks, tradeoffs, and open questions

If the task is code-related, include exact file paths, likely test targets, and verification steps.

## Save location

Save the plan with `write_file` under:
- `.hermes/plans/YYYY-MM-DD_HHMMSS-<slug>.md`

Treat that as relative to the active working directory / backend workspace. Hermes file tools are backend-aware, so using this relative path keeps the plan with the workspace on local, docker, ssh, modal, and daytona backends.

If the runtime provides a specific target path, use that exact path.
If not, create a sensible timestamped filename yourself under `.hermes/plans/`.

## Interaction style

- If the request is clear enough, write the plan directly.
- If no explicit instruction accompanies `/plan`, infer the task from the current conversation context.
- If it is genuinely underspecified, ask a brief clarifying question instead of guessing.
- After saving the plan, reply briefly with what you planned and the saved path.

---

## Multi-Project Orchestration

When the user asks you to plan work across **multiple independent projects** (codebases with separate repos, build systems, and launch plans):

### Initial Assessment

1. **Verify against files, not documents.** Handover docs, specs, and READMEs drift faster than code. Before planning work against a documented state, run `ulimit -n 2048 && pytest -q --tb=short` (or the project's equivalent test command) and grep for key features. The codebase you find may be far ahead of the docs you read.

2. **Prioritise fast by revenue-readiness.** If one project has a proven engine, an existing storefront, and a clear money-delivery path while another is still proving its core utility, the closer-to-revenue project should be the focus of the nitty-gritty build work.

3. **Narrow the scope immediately.** When the user says "check the state of my projects," do NOT scan the entire filesystem. Ask which projects they mean, or list only the ones you already know about from memory. A broad `find ~` wastes time and frustrates.

### Architecture Review Before Cross-Language Implementation

When a design crosses multiple programming languages (Python, TypeScript, .NET, etc.):

**Do not implement first and review later.** The user's explicit pattern is: architecture review BEFORE applying across projects. Violating this costs trust.

1. **Design the cross-language contract FIRST.** What format do all languages share? (Answer: the receipt JSONL). What is language-specific? (Answer: spec format, verifier, signing library). Build the contract, then the language-specific implementations — not the other way around.

2. **The receipt IS the bridge.** Every language writes JSONL receipts to `.lux/receipts/`. The CI gate only reads receipts — it doesn't care what language wrote them. This keeps the enforcement layer language-agnostic.

3. **Enforce PDD at CI level, not language level.** One shell script reads modified files from git, checks `.lux/receipts/<today>.jsonl` for a PASS receipt on each, exits 1 if missing. Works for Python, TS, .NET — anything that can write JSON to a file.

4. **Do NOT port a language-specific tool to every language.** Building `lux spec` in TypeScript and then porting it to Python and C# is wrong. Instead: each language has its own spec format (TS `FunctionSpec`, Python dataclasses, C# attributes). The *receipt* is the shared contract. The CI gate is one script.

**Pitfall from 2026-06-17:** I built the `lux spec` CLI (TypeScript), deployed `popdd_agent.py` (Python), and started talking about `dotnet-popdd` before having an architecture review. The user called this out: "we have been focusing on python when we also have .net projects." The fix is to design the language-agnostic contract (receipt JSONL → CI gate) before building any language-specific tool.

See `references/cross-language-architecture-review.md` for the full pattern with worked example.

### Stale-Docs Audit Pattern

When a handover document suggests the codebase is immature in certain areas, run a **parallel subagent audit** before planning:

```python
delegate_task(
    tasks=[
        {
            "goal": "Audit whether feature X, Y, Z are actually built.",
            "context": f"Project at {project_path}. Handover doc says {claims}. Check actual files.",
            "toolsets": ["terminal", "file"],
        },
        # ... up to 3 concurrent tasks
    ]
)
```

This catches "documented as unfinished, actually built" or vice versa, and prevents planning against stale assumptions. (See `references/stale-docs-audit.md` for the full pattern with exact commands.)

### Autonomous Execution (with Prove-Everything Discipline)

When the user says "take over the planning, only involve me for critical decisions":

1. **Flag only irreversible/high-cost decisions** to the user. Do this in a single structured question with bullet-point options — not a back-and-forth. A decision that costs time to reverse (hosting provider, content storage, payment provider) needs input. A decision that costs a few minutes to fix (test broken, config mismatch, missing CI) does NOT.
2. **Proceed immediately** on everything that doesn't need a decision. Fix broken tests, fix config mismatches, write CI, audit code — these don't need approval.
3. **Prove what you build.** Every claim ("test suite passes", "CORS is wired", "ContentVersion is fixed") must be backed by tool output — pytest run output, grep results, or direct verification. Never deliver unverified statements. "It should work" is not a deliverable.
4. **Batch user questions into one structured message.** If a decision is needed, collect everything into a single message with bullets, not a back-and-forth. Let the user unblock multiple tasks with one answer.
5. **Re-evaluate the plan after each phase.** When one workstream finishes, the remaining gaps may have shrunk enough to launch. Don't blindly execute the next phase — check what's actually left.
6. **Learn and evolve.** If a correction from the user surfaces a better way, update the plan skill immediately (not at the end of the session). The skill should get better every time it's used.
7. **Use judgment on priority.** When working on multiple projects, prioritise the one closest to revenue or launch. A project with a proven engine and an existing storefront gets more build work than one still proving its core utility. See `references/autonomous-project-prioritization.md`.

---

# Writing the Plan Well

The rest of this skill is the craft of authoring a *good* implementation plan — the content that goes inside the markdown file above.

## Overview

Write comprehensive implementation plans assuming the implementer has zero context for the codebase and questionable taste. Document everything they need: which files to touch, complete code, testing commands, docs to check, how to verify. Give them bite-sized tasks. DRY. YAGNI. TDD. Frequent commits.

Assume the implementer is a skilled developer but knows almost nothing about the toolset or problem domain. Assume they don't know good test design very well.

**Core principle:** A good plan makes implementation obvious. If someone has to guess, the plan is incomplete.

## When a Full Implementation Plan Helps

**Always use before:**
- Implementing multi-step features
- Breaking down complex requirements
- Delegating to subagents via subagent-driven-development

**Don't skip when:**
- Feature seems simple (assumptions cause bugs)
- You plan to implement it yourself (future you needs guidance)
- Working alone (documentation matters)

## Bite-Sized Task Granularity

**Each task = 2-5 minutes of focused work.**

Every step is one action:
- "Write the failing test" — step
- "Run it to make sure it fails" — step
- "Implement the minimal code to make the test pass" — step
- "Run the tests and make sure they pass" — step
- "Commit" — step

**Too big:**
```markdown
### Task 1: Build authentication system
[50 lines of code across 5 files]
```

**Right size:**
```markdown
### Task 1: Create User model with email field
[10 lines, 1 file]

### Task 2: Add password hash field to User
[8 lines, 1 file]

### Task 3: Create password hashing utility
[15 lines, 1 file]
```

## Plan Document Structure

### Header (Required)

Every plan MUST start with:

```markdown
# [Feature Name] Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** [One sentence describing what this builds]

**Architecture:** [2-3 sentences about approach]

**Tech Stack:** [Key technologies/libraries]

---
```

### Task Structure

Each task follows this format:

````markdown
### Task N: [Descriptive Name]

**Objective:** What this task accomplishes (one sentence)

**Files:**
- Create: `exact/path/to/new_file.py`
- Modify: `exact/path/to/existing.py:45-67` (line numbers if known)
- Test: `tests/path/to/test_file.py`

**Step 1: Write failing test**

```python
def test_specific_behavior():
    result = function(input)
    assert result == expected
```

**Step 2: Run test to verify failure**

Run: `pytest tests/path/test.py::test_specific_behavior -v`
Expected: FAIL — "function not defined"

**Step 3: Write minimal implementation**

```python
def function(input):
    return expected
```

**Step 4: Run test to verify pass**

Run: `pytest tests/path/test.py::test_specific_behavior -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/path/test.py src/path/file.py
git commit -m "feat: add specific feature"
```
````

## Writing Process

### Step 1: Understand Requirements

Read and understand:
- Feature requirements
- Design documents or user description
- Acceptance criteria
- Constraints

### Step 2: Explore the Codebase

Use Hermes tools to understand the project:

```python
# Understand project structure
search_files("*.py", target="files", path="src/")

# Look at similar features
search_files("similar_pattern", path="src/", file_glob="*.py")

# Check existing tests
search_files("*.py", target="files", path="tests/")

# Read key files
read_file("src/app.py")
```

### Step 3: Design Approach

Decide:
- Architecture pattern
- File organization
- Dependencies needed
- Testing strategy

### Step 4: Write Tasks

Create tasks in order:
1. Setup/infrastructure
2. Core functionality (TDD for each)
3. Edge cases
4. Integration
5. Cleanup/documentation

### Step 5: Add Complete Details

For each task, include:
- **Exact file paths** (not "the config file" but `src/config/settings.py`)
- **Complete code examples** (not "add validation" but the actual code)
- **Exact commands** with expected output
- **Verification steps** that prove the task works

### Step 6: Review the Plan

Check:
- [ ] Tasks are sequential and logical
- [ ] Each task is bite-sized (2-5 min)
- [ ] File paths are exact
- [ ] Code examples are complete (copy-pasteable)
- [ ] Commands are exact with expected output
- [ ] No missing context
- [ ] DRY, YAGNI, TDD principles applied

## Principles

### DRY (Don't Repeat Yourself)

**Bad:** Copy-paste validation in 3 places
**Good:** Extract validation function, use everywhere

### YAGNI (You Aren't Gonna Need It)

**Bad:** Add "flexibility" for future requirements
**Good:** Implement only what's needed now

```python
# Bad — YAGNI violation
class User:
    def __init__(self, name, email):
        self.name = name
        self.email = email
        self.preferences = {}  # Not needed yet!
        self.metadata = {}     # Not needed yet!

# Good — YAGNI
class User:
    def __init__(self, name, email):
        self.name = name
        self.email = email
```

### TDD (Test-Driven Development)

Every task that produces code should include the full TDD cycle:
1. Write failing test
2. Run to verify failure
3. Write minimal code
4. Run to verify pass

See `test-driven-development` skill for details.

### Frequent Commits

Commit after every task:
```bash
git add [files]
git commit -m "type: description"
```

## Common Mistakes

### Vague Tasks

**Bad:** "Add authentication"
**Good:** "Create User model with email and password_hash fields"

### Incomplete Code

**Bad:** "Step 1: Add validation function"
**Good:** "Step 1: Add validation function" followed by the complete function code

### Missing Verification

**Bad:** "Step 3: Test it works"
**Good:** "Step 3: Run `pytest tests/test_auth.py -v`, expected: 3 passed"

### Missing File Paths

**Bad:** "Create the model file"
**Good:** "Create: `src/models/user.py`"

## Execution Handoff

After saving the plan, offer the execution approach:

**"Plan complete and saved. Ready to execute using subagent-driven-development — I'll dispatch a fresh subagent per task with two-stage review (spec compliance then code quality). Shall I proceed?"**

When executing, use the `subagent-driven-development` skill:
- Fresh `delegate_task` per task with full context
- Spec compliance review after each task
- Code quality review after spec passes
- Proceed only when both reviews approve

## Remember

```
Bite-sized tasks (2-5 min each)
Exact file paths
Complete code (copy-pasteable)
Exact commands with expected output
Verification steps
DRY, YAGNI, TDD
Frequent commits
```

**A good plan makes implementation obvious.**
