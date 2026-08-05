---
name: safe-commit-protocol
description: Use when a session ends or pauses with N>0 uncommitted files in the working tree — especially when N>10, when the user says "we don't want to lose any work" / "this needs careful review" / "audit the dirty tree", or when a parallel agent may have left work behind. Provides the identify-mine-vs-theirs, dependency-grouped, atomic-or-split commit decision protocol that protects parallel work without corrupting intermediate states.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [git, commit, dirty-tree, parallel-agents, audit, preservation, dependency-order]
    related_skills: [github-pr-workflow, task-resilience, dropped-ball-prevention, simplify-code]
---

# Safe Commit Protocol — Dirty Tree Audit & Preservation

The safe-commit protocol is what to do when a session ends (or pauses) with a non-trivial working tree and the user has flagged preservation risk. The user signal that triggers this skill is one of:

- *"We don't want to lose any work"*
- *"This needs careful review"*
- *"Audit the dirty tree"*
- *"What's actually uncommitted?"*
- *"Don't lose the parallel agent's work"*

The protocol preserves both the user's own work AND any work a parallel agent (Claude, codex, opencode) may have left behind — without breaking intermediate imports.

## When to Use

Trigger when:

- `git status --short | wc -l` returns > 5 files modified or untracked
- The user has expressed preservation concern (verbal or implied)
- A `delegate_task` subagent is still running and may have written files
- Multiple commits ago the tree was clean; now it isn't
- The session is being interrupted (timeout, /stop, new topic) with work in flight

Do NOT trigger for:

- Single-file edits where you know exactly what changed
- Work where you have a recent uncommitted edit and no parallel work
- Routine commit-and-push cycles

## The Protocol (5 phases)

### Phase 1 — Inventory

Capture the current state. The exact command matters — `git status` alone is not enough; you need both modified and untracked, separately:

```bash
# Modified files only
git status --short | awk '$1 ~ /^M$/ {print $2}'

# New untracked files
git status --short | awk '$1 == "??" {print $2}'

# Both, with status code
git status --short
```

Also grab the recent commit log so you know what *you* already shipped:

```bash
git log --oneline -10
git show --name-only --pretty='' HEAD
```

### Phase 2 — Identify mine vs. theirs

If you made commits in this session, your files are in the latest commit's stat. Anything else in the dirty tree is either your uncommitted work OR parallel-agent work:

```python
import subprocess
r = subprocess.run(['git', 'show', '--name-only', '--pretty=', 'HEAD'],
                   capture_output=True, text=True)
my_files = set(r.stdout.strip().split('\n'))

# Compare against dirty tree
r2 = subprocess.run(['git', 'status', '--short'], capture_output=True, text=True)
for line in r2.stdout.strip().split('\n'):
    if not line.strip(): continue
    path = line.split()[-1]
    marker = '[MINE]' if path in my_files else '[NOT MINE]'
    print(f'  {path}{marker}')
```

`[NOT MINE]` files are the parallel-agent's. **They MUST be preserved.** A "we don't want to lose any work" complaint is often specifically about preserving parallel work.

### Phase 3 — Verify the dirty tree is internally consistent

Before committing anything, prove the dirty tree imports. Run a fast import smoke test for every modified module:

```python
# For Python projects
import subprocess
dirty = ['gateway/operator_shell/cockpit.py', 'gateway/operator_shell/estate.py', ...]
modules = [f.replace('/', '.').replace('.py', '') for f in dirty if f.endswith('.py')]
for m in modules:
    try:
        __import__(m)
        print(f'OK  {m}')
    except Exception as e:
        print(f'FAIL {m}: {e}')
```

If any module fails, the dirty tree is in a broken intermediate state — STOP and surface to the user. Do not commit broken code.

For other languages, equivalent: `cargo check`, `go build ./...`, `tsc --noEmit`, `mvn compile`, etc.

### Phase 4 — Group by dependency, decide atomic or split

Build the dependency graph using `grep` for imports:

```bash
grep -nE '^from gateway\.operator_shell\.|^import gateway\.operator_shell' \
  gateway/operator_shell/*.py
```

Foundation files (those that export symbols used by many others) commit first. In a typical refactor:

```
panel_chrome.py           <- defines panel_stamp, VERDICT_GLYPHS, Group, compose
cockpit.py, estate.py,    <- consume those exports
mission.py, builds.py,    <- consume them too
telegram.py, run.py       <- the wiring (imports everything)
tests/                    <- one per implementation file
```

**The atomic-vs-split decision rule:**

| Condition | Decision |
|---|---|
| Files have mutual dependencies (foundation exports → consumers) | **One atomic commit** with a message explaining why-atomically |
| Files are independent (no cross-imports) | **Split into per-file or per-feature commits** |
| Mixed (some independent, some coupled) | **2-3 commits**, dependency-ordered |
| Unsure which is which | **Atomic**, document the coupling in the message |

The user's "we don't want to lose any work" beats commit granularity. **When in doubt, atomic.**

A commit message for an atomic commit should explicitly document the coupling:

```
operator_shell: world-class cockpit — 4-spine nav, panel_stamp, 'now' alias, preflight cache

This commit is large because the changes are tightly coupled — splitting
leaves intermediate states where `panel_stamp`, `VERDICT_GLYPHS`, `Group`,
or `cache_get` are referenced but not yet defined. One commit = one
coherent ship.
```

### Phase 5 — Commit and verify

Stage only the files you intend to commit (never `git add .` in a dirty tree — that's how you accidentally lose parallel work):

```bash
git add <file1> <file2> ...
git status --short        # confirm ONLY intended files are staged
```

Then commit. **Watch the shell unicode escape pitfall** documented in
`github-pr-workflow`: emoji in commit messages get shell-escaped to `\uXXXX`
sequences. Use `git commit -F /tmp/msg.txt` or `git commit -F -` with
stdin, never `-m` directly in a `terminal()` call:

```bash
# Safest: write the message to a file first
cat > /tmp/msg.txt <<'EOF'
operator_shell: categorized /help directory

🎛 Hermes Command Directory...

EOF
git commit --no-verify -F /tmp/msg.txt
```

After committing:

1. `git status --short` — should be empty (or only intentional remaining)
2. `git log --oneline -3` — confirm new SHA exists
3. `git log --format=%B <new_sha> -1` — verify emoji survived (no `\uXXXX`)
4. Run the targeted test suite for the changed area — confirm no regressions

If step 3 shows escaped emoji, amend the commit using stdin:

```bash
git commit --amend -F /tmp/msg.txt
# or via Python:
python3 -c "
import subprocess
msg = open('/tmp/msg.txt', 'rb').read()
subprocess.run(['git', 'commit', '--amend', '-F', '-'], input=msg)
"
```

## Pitfalls (Real Session Lessons)

### Don't `git add .` in a dirty tree

`git add .` (or `-A`) stages EVERYTHING, including parallel-agent files
that may not be ready. You lose the ability to selectively commit. In a
dirty tree, always `git add <explicit file list>`.

### Atomic commits can be large

A 30-file atomic commit with a 1000-line diff is fine **if the coupling
justifies it**. The test is: would splitting leave intermediate states
that don't import? If yes, atomic is correct. If no, you're probably
being lazy — split and document each commit's purpose.

### Don't commit the user's uncommitted debug state

If the user has `print("DEBUG")` statements scattered around, surface
them, don't commit. The audit is for parallel-agent work and your own
intentional changes; it's not for orphan debug.

### Don't bypass pre-commit hooks with `--no-verify` unless needed

`--no-verify` is appropriate when the pre-commit hook has a known timeout
issue (the agent's terminal timeout is 30-60s; pre-commit tests often
take 40s+). Default to running the hook. If you must skip, document why
in the commit message.

### The "mine vs theirs" check is mandatory

Skipping Phase 2 leads to "I accidentally committed parallel work I didn't
review." Five minutes of grep saves hours of "wait, what did I ship?"

### Shell unicode escape in commit messages

Already documented in `github-pr-workflow` pitfall. Always use `-F file`
or `-F -`, never `-m "emoji text"` in a `terminal()` call.

## When to Split vs. Atomic (Decision Examples)

| Scenario | Decision |
|---|---|
| 5 unrelated typo fixes | **Split** — 5 commits, one per file |
| Refactor of one module across 10 files | **Split** — but in dependency order (foundation first) |
| New feature that touches UI + backend + tests + docs | **One commit** if the feature doesn't work without all parts |
| Parallel-agent work + your own uncommitted debug | **Two commits** — theirs first (atomic, large), then yours |
| Worktree from a `delegate_task` that's still running | **STOP** — do not commit, the agent may still be writing |
| Pre-commit hook broken (timeout) | **`--no-verify`** — commit, document in message |

## Verification Checklist

- [ ] `git status --short` empty after commit
- [ ] `git log --format=%B <sha>` shows real emoji (no `\uXXXX` escape sequences)
- [ ] `git show --stat <sha>` shows only intended files
- [ ] Targeted test suite passes
- [ ] Commit message explains "why atomic" if files > 10
- [ ] No `print("DEBUG")` or `TODO` statements accidentally shipped

## Companion Skills

- **`github-pr-workflow`** — PR lifecycle, including the shell-unicode-escape pitfall
- **`task-resilience`** — broader process discipline, the "default to parallel" rule
- **`dropped-ball-prevention`** — Otto's hard rules; this skill extends them with the preservation specifics
- **`simplify-code`** — post-commit cleanup pass; different scope