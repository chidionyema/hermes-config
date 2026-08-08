---
name: github-operations
description: "Operate GitHub repositories end to end: authenticate, inspect and manage repositories, issues, pull requests, reviews, branches, releases, and CI with gh or the REST API."
version: 1.0.0
author: Hermes Agent
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [github, gh, git, issues, pull-requests, code-review, repositories, releases, authentication]
---

# GitHub Operations

Use this class skill for the complete GitHub lifecycle rather than selecting a tool-specific skill.

## Authentication
- Prefer `gh auth status`; authenticate with `gh auth login` or a narrowly scoped token.
- Verify the active host/account before mutating anything.
- Never print tokens; use SSH or gh's credential store where possible.

## Repository and remote management
- Inspect remotes, default branches, permissions, and repository metadata before cloning, forking, creating, or changing remotes.
- Preserve existing remotes unless the user explicitly requests replacement.
- For releases and branch operations, confirm target repository and branch first.

## Issues and project intake
- Search before creating duplicates; capture labels, assignee, milestone, and reproduction evidence.
- Triage with labels and state transitions, and keep issue bodies actionable.

## Pull requests and review
- Inspect the complete diff, checks, comments, and mergeability.
- Separate review findings from workflow actions; report file/line, impact, confidence, and fix.
- Do not merge or close without explicit authorization when the request only asks for review.

## Safe lifecycle
1. Identify repository and scope.
2. Read current state and permissions.
3. Perform the smallest mutation.
4. Verify via `gh` output/API and report durable URLs or IDs.

## Tool selection
Use `gh` for normal operations; use REST/GraphQL only when gh lacks the needed field. Keep provider-specific recipes in references when they become lengthy.
