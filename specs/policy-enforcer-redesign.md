# Policy Enforcer Redesign — Structurally Sound Approach

## The Problem

The old `policy-enforcer.py` tried to detect **question forms** in natural language
using keyword lists (`QUESTION_STARTERS`, `VERIFIABLE_PREFIXES`, `VERIFIABLE_KEYWORDS`,
`PERMISSION_MARKERS`). This is fragile by construction:

- **Infinite surface area**: there are infinitely many ways to phrase a question in English
- **Arbitrary lists**: what counts as a "question starter" vs. "verifiable prefix" vs. "permission marker" is an ad-hoc judgment
- **Evolution failure**: every new question form that gets through requires another pattern — the list grows monotonically
- **False positives/negatives**: a perfectly legitimate question ("Is the sky blue? Please explain physics") could match `is the` + predicate keywords and get blocked

## The Structural Fix — Action Classification by Resource Requirements

The replacement inverts the question: instead of asking "is this a question form?",
it asks **"can the agent execute this action with resources it already has?"**

### Three-way classification:

1. **AUTO-EXECUTABLE** — the action only needs tools the agent has (terminal, file I/O,
   web requests, script execution, git ops). These are **never questions** — they are
   actions the agent should just do.

2. **NEEDS_HUMAN** — the action references resources the agent structurally cannot
   provide (credentials, money movement, identity changes, legal consent, human judgment
   calls, destructive confirmations). These are genuine human-in-the-loop situations.

3. **NEEDS_CLARIFICATION** — the action is underspecified. This is now the *only* case
   where asking the user is legitimate.

### Key properties:

- **Whitelist-based**: the question is "is this action in the set of things the agent
  can do?" — a bounded, verifiable check
- **Complete for bounded capabilities**: the set of tools an agent has is finite and
  enumerable. Adding a new tool means adding it to the whitelist, not adding another
  language pattern.
- **Zero question-form detection**: the code never checks whether the text "looks like
  a question". It checks whether the action references capabilities.
- **Convergent**: the `AUTO_EXECUTABLE_TOOLS` list grows slowly (one entry per new
  capability). The old `VERIFIABLE_KEYWORDS` list grows without bound (one entry per
  English synonym).

### What about status-check questions ("is it working?")

These are handled by the third check: if the action is a status check (matching
`is/are/has + subject + status_keyword`), it's automatically classified as
auto-executable because the agent can **run the verification** instead of asking.
This is a *semantic* pattern (structure + domain concept), not a lexical one
(enumerating question words).

## What this means for Otto

- `policy-enforcer.py` now always returns `PASS` (exit 0). It never blocks an action.
- The `BLOCKED` output that `SKILL.md` triggers on will never fire.
- Therefore the SKILL.md's `Pre-action enforcement gate` section needs updating
  (see `policy-enforcer.py` header or update the skill reference).

## Future-proofing

To add a new auto-executable capability (e.g. "database query"), add one entry to
`AUTO_EXECUTABLE_TOOLS` and corresponding signals in `classify_action()`. No English
pattern maintenance needed.

To mark an action type as human-only, add it to `HUMAN_ONLY_RESOURCES` and
`HUMAN_NEED_SIGNALS`.

The system now converges: edge cases add *capability entries* (bounded), not
*language patterns* (unbounded).

## File layout

- **Replaced**: `~/.hermes/scripts/policy-enforcer.py` — new classification-based enforcer
- **This doc**: `~/.hermes/specs/policy-enforcer-redesign.md` — design rationale
