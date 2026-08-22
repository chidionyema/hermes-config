---
name: crew-orchestration
description: "Report and drive a tracked build from Telegram: checkpoint status, blockers, verification history, and passing a founder request into the crew's GitHub issue. Use for /status on a build, \"how is the build going\", \"what is blocked\", or when the founder asks for something while away from the laptop."
version: 1.0.0
author: Hermes Agent
platforms: [macos, linux]
metadata:
  hermes:
    tags: [crew, delivery, github, issues, bdd, behave, status, telegram]
---

# Crew orchestration

A conversation with the founder becomes a GitHub issue with a checkpoint
checklist. Engineering builds and posts evidence. A QA agent runs the `behave`
suite and is the only role that can tick a box. Hermes is a **surface** onto
that issue, not a fourth agent: it reads the board and posts requests into it.

The tool is `crew`, at `~/.local/bin/crew`. Source and roles:
`~/dev/code/crew`. The spec is `~/dev/code/crew/CREW_ORCHESTRATION_SPEC.md`.

Every command runs inside the repo being built. Today that is
`~/dev/code/survival-stack`.

## Status, already formatted for Telegram

```bash
cd ~/dev/code/survival-stack && crew status --format telegram
```

Send that output as-is — it is short and already Markdown. Example:

```
*#1 Build: Survival Stack*
WORKING — 1/5
CP1 ✅ CP2 ⏳ CP3 ⏳ CP4 ⏳ CP5 ⏳
```

## Detail, when the founder asks for more than the counts

```bash
cd ~/dev/code/survival-stack && crew status --format json
```

The JSON carries every checkpoint, the verification log with commit SHAs, and
the blocker list. Quote the blocker text verbatim; do not summarise it away.

## Pass a founder request to the crew

The founder says "re-run the cold start check" or "cold start on vultr". Hermes
does not run it. Hermes writes it where engineering will see it:

```bash
cd ~/dev/code/survival-stack && CREW_ROLE=hermes crew comment "founder asked from Telegram: <his words>"
```

Then reply: "Posted to #N. Engineering picks it up."

## What Hermes must never do

- **Never `crew verify`.** Verification runs where the repository and the lab
  are, at a known commit. A verification triggered from a chat handler is a
  green tick nobody can trace.
- **Never edit the issue body.** `crew` owns it and rebuilds it whole on every
  write; a hand edit deletes another agent's state.
- **Never report a status you did not read.** If `crew status` errors, send the
  error text.

## Why a tick can be trusted

Three refusals, each mechanical:

1. `crew evidence` cannot tick a box — engineering can only report.
2. `crew verify` refuses the role that posted the evidence.
3. A run matching zero scenarios is a FAIL. `behave` exits 0 on an unmatched
   tag, and a tick from an empty run is the worst outcome available.
