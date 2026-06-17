---
name: external-audience-writing
description: "Write documents for audiences OUTSIDE the project — hiring managers (CVs, cover letters), potential contributors (READMEs, package intros), conference reviewers (talk abstracts), investors (pitches), recruiters (LinkedIn bios). The hard rule: translate your private brand vocabulary (project names, internal jargon, your protocol names) into the audience's industry vocabulary. Personal projects are subsumed into skills. Numbers stay, names get dropped. Load when the user asks for help with a CV, cover letter, LinkedIn bio, README intro for a public package, talk abstract, or pitch deck where the audience doesn't already know the project names."
version: 1.0.0
author: LUX Engine
license: MIT
metadata:
  hermes:
    tags: [writing, audience, cv, bio, linkedin, readme, pitch, vocabulary, translation]
---

# External Audience Writing — Vocabulary Translation & Skill Framing

The class of writing where **the audience doesn't share your context**. You built it, you named it, you know what HMAC-SHA256 or DecisionReceipt or POPDD means — they don't. A hiring manager's first scan of your CV is a filter, not a deep read. A recruiter on LinkedIn decides in 6 seconds whether to scroll past.

## The Core Rule: Translate, Don't Transcribe

When you write something for an external audience, **the artifact is for them, not for you.** Your internal naming, your internal jargon, your project's brand — those serve *your* clarity while you're building. They become friction when a stranger is reading.

| You say (internal) | They expect (industry) |
|---|---|
| POPDD (Proof of Proof-Driven Development) | "a cryptographic chain-of-custody protocol for AI agent actions" |
| LUX | drop the name, say "a TypeScript proof-driven development toolchain" |
| DecisionReceipt | "signed, hash-chained audit records" or just "audit records" |
| previousHash | "hash-chained" or drop entirely |
| Curry-Howard | "type-level proofs using the type system" |
| Property-based testing | keep — Hypothesis / QuickCheck vocabulary, widely understood |
| Dafny/Z3 | keep — formal verification community vocabulary |
| HMAC-SHA256, Ed25519 | keep — every senior backend engineer recognises these |
| Pi, Aider, Claude Code, DeepSeek | keep if relevant — these ARE the tools |

**The test:** for every proper noun and acronym in your draft, ask *"would a senior engineer in this domain recognise this in 2 seconds?"* If no → translate. If yes → keep.

## Skills vs Projects

A CV is a **skills document**, not a **portfolio document**. Same goes for most LinkedIn bios and most cover letters. The shift:

| Portfolio framing (wrong for hiring-manager CV) | Skills framing (right) |
|---|---|
| "Built LUX, a TypeScript proof-driven development engine, 81 tests, public on GitHub" | "Built and shipped a TypeScript proof-driven development toolchain: property-based testing, type-level proofs, Dafny/Z3 mechanized verification" |
| "Maintained @lux/popdd and lux-popdd, two cryptographic libraries with 39 tests" | "Maintainer of two HMAC-chained cryptographic libraries (TypeScript and Python) with 39 tests across both" |
| "Built Prospector (Python, 359 tests, pre-launch with payments+fulfilment+delivery)" | drop entirely or fold into "Built and shipped multiple production Python services..." |
| URLs to personal repos (`github.com/me/project`) | drop — even in a personal-projects section. The URL is a separate decision; the hiring manager doesn't follow links. If the user later asks for links, add them in a final pass. |

**Why drop personal-repo URLs from CVs by default:** the CV is a skills document, not a portfolio. A hiring manager scanning the CV reads `https://github.com/...` as personal-project scope and skips it. The right place for URLs is the LinkedIn profile, the portfolio site, or the cover letter — places where clicking through is the expected action. If the user wants the URLs in the CV, they will say so after seeing the redline without them. The reversibility is cheap (add them back); the cost of including them by default is real (the audience reads them as filler).

**The exception:** when the audience explicitly wants a portfolio (an investor pitch, a conference talk where the project IS the talk, a GitHub README that's the project's landing page), then names + URLs + "what it does for users" all belong. The same artifact gets framed differently for different audiences.

## Audience Cheat-Sheet

| Audience | What they scan for | What to keep | What to drop |
|---|---|---|---|
| **Hiring manager (CV)** | Years of experience, stack match, leadership, quantified impact | Tech names (HMAC, Dafny/Z3, K8s), numbers (tests, LOC, services), methodologies (TDD, formal verification) | Project brand names, repo URLs, "I built X" claims, anything that reads like a portfolio |
| **Recruiter (LinkedIn bio)** | Title, current role, top 3 skills, location | Job title, current company, 2-3 skill keywords, industries | Personal project names, deep technical detail, anything that doesn't survive the 6-second skim |
| **Conference reviewer (talk abstract)** | Originality, relevance to conference theme, audience takeaway | Topic, your unique angle, what attendees will learn | Your project name (unless the talk IS the project), your company's name (if confidential) |
| **Open-source maintainer (README)** | What it does, why use it, install/quickstart, contribution path | Project name (it IS the project), features, install commands, license, examples | Internal jargon from your team, "TODO: write better README later" filler, anything that needs context to parse |
| **Investor (pitch)** | Problem, solution, traction, market | Market size, traction numbers, the problem statement, what makes you defensible | Technical architecture details, internal acronyms, your favourite engineering tool |

## When to Insert vs When to Rewrite

For documents the user already owns (CV, existing LinkedIn bio, existing README), the redline discipline from `task-resilience` applies:

1. **Default to insert-only.** Add the missing skills, don't rewrite the existing voice.
2. **Present a gap analysis first**, wait for greenlight.
3. **Write to a new file**, never patch the canonical in place.
4. **Verify byte-identity of the original** before AND after the edit.

But for documents being created from scratch (a new pitch, a new talk abstract), the discipline is different:

1. **Ask the audience question first.** "Who's reading this?" determines vocabulary, length, and structure.
2. **Draft to the audience's vocabulary**, not yours.
3. **Cut and re-cut.** The first draft is too long and too jargon-heavy for external reading. Three rounds of "what would a smart stranger need to know?" usually lands the right density.

## The "Use Your Judgment" Trap

When the user gives a one-word answer to a multi-question prompt (e.g. "2"), the natural impulse is to guess the option they meant. The safer pattern:

1. **State your interpretation** explicitly: "I read '2' as the second option of the second question (write to a new file). If you meant something else, say so."
2. **Pick the conservative default**: for vocabulary questions, default to MORE translation (more brand-name removal) not less, because over-translating is reversible (add names back) while under-translating reads as jargon to the audience.
3. **Make it reversible**: always keep the original intact, never patch in place.

## Worked Anti-Patterns

**Anti-pattern: "I built LUX, a TypeScript proof-driven development engine, 81 tests, public on GitHub"**
Why it's wrong: the hiring manager's filter doesn't recognise "LUX" — it sees an unknown proper noun and skips. The 81 tests number is great context for a technical phone screen, useless in a CV scan. The "public on GitHub" reads as a personal project, which the user later confirmed employers don't care about.

Right rewrite: "Built and shipped a TypeScript proof-driven development toolchain: property-based testing, type-level proofs using the type system, Dafny/Z3 mechanized verification. Includes a spec linter that statically catches the precondition-throws-on-undefined bug class."

The technology is still named (TypeScript, Dafny/Z3). The skills are still specific. But the project's brand is gone — a hiring manager who knows Dafny/Z3 will recognise "this person has done serious formal verification work" without needing to chase a project name.

**Anti-pattern: "POPDD (Proof of Proof-Driven Development), DecisionReceipt, previousHash"**
Why it's wrong: these are *your* protocol names. They're not RFC standards. They don't appear in job descriptions. A hiring manager reads them as invented acronyms and assumes personal-project scope.

Right rewrite: "a cryptographic chain-of-custody protocol for AI agent actions: signed, hash-chained audit records (HMAC-SHA256, pluggable Ed25519)". Every term in there is industry-standard.

## The "Sprinkle, Don't Section" Rule

When a hiring manager reads a CV top-down, **a top-level section heading reads as "this is what I specialise in."** If the section is "AI & Agentic Tooling" placed at the top after Profile, the reader infers: "this person is an AI tooling specialist." That's wrong if the actual job is backend / platform / infra.

**The fix:** don't create a top-level section for AI/agentic content. Instead, **sprinkle** those bullets into the most recent role entry as work done in that role. A bullet under "Senior Engineer at Company X, 2024-present" reads as "this is what I did at my current job." Same content, completely different audience interpretation.

Worked example from a 2026-06-17 CV redline:

**Wrong (top-level section, reads as specialist):**
```
AI & Agentic Tooling
  Built a cryptographic chain-of-custody protocol for AI agent actions: ...
  Operate multi-model agent workflows daily: ...
Verification & Quality Engineering
  Source-or-die invariant: ...
Open Source
  Maintainer of two HMAC-chained cryptographic libraries ...
```

**Right (sprinkled into current role):**
```
Senior Full Stack Engineer, OSL Technologies  June 2024 - Present
  ... existing role bullets ...
  Operate multi-model agent workflows (Pi, Aider, Claude Code, DeepSeek) ...
  Built and operate a cryptographic chain-of-custody audit log ...
  Drove adoption of proof-driven development practices ...
  Maintainer of two HMAC-chained cryptographic libraries ...
```

**The signal flip:** the same words read as "AI specialist" in section form and as "engineer who used AI tools at work" in role form. The CV's job is to land the interview for the role you're applying to, not to advertise the niche you're personally most excited about. Always check: **does a top-level section heading here make me sound like a specialist in something the job doesn't ask for?** If yes, sprinkle.

**The exception:** when the role IS the specialty (Staff AI Engineer, Agentic Tools Engineer, Open-Source Maintainer at a foundation), top-level sections are correct because the audience is looking for that specialist signal. The same content gets framed differently for different roles.

## Drop Insufficient-Evidence Subsections

A subsection in a CV is a **claim about your skills**. Every claim invites verification. If the subsection can't be backed up by the rest of the document, **drop it**.

Worked example from the same 2026-06-17 CV:

**Original CV had a Core Skills subsection:**
```
Machine Learning & Data Analysis
  Machine Learning: Experience in developing machine learning models and clustering algorithms, particularly in data analysis, feature extraction, and correlation analysis for predictive analytics.
```

**The rest of the CV backed this up weakly:** exactly one ML cert (Imperial Business School 2023-24), one mention of "prototyping ML models for threat detection" at OSL. The subsection was 1 sentence of fluff claiming breadth that the rest of the document didn't deliver.

**Right move: drop the subsection.** A phone screen will probe "tell me about your ML experience" and the answer will be thin. Better to not raise the question than to fail it.

**The test for every Core Skills subsection:** can I name 3+ concrete pieces of evidence (projects, employment bullets, certs) that back up this subsection? If yes, keep it. If no, drop or rewrite to match the evidence.

## Personal Projects: Default Off, Exception On

Strongest user-correction signal of the 2026-06-17 session: when asked to add missing skills, the user pushed back on including personal projects:

> *"I don't need to expose my persona projects on cv, employers don't care, just need to reflect modern ai engineering and agentic coding skills"*

The default for a hiring-manager CV: **personal projects section is OFF.** Drop it entirely. Don't even include project names. Don't include URLs. Don't include "Selected Personal Projects" headings.

The argument:
1. A personal-projects section signals "this person spends off-hours on side projects" — neutral-to-negative in a hiring-manager filter
2. The same content (POPDD chain-of-custody, TypeScript proof-driven dev, HMAC libraries) reads as skills when phrased generically
3. The URL goes in the LinkedIn profile where clicking through is the expected action; the CV doesn't get clicked
4. "Public on GitHub" reads as personal-project scope, not as production-shipped code

**The exceptions:**
- The user explicitly asks for personal projects (they may want a portfolio CV for a specific application)
- The role is open-source maintainer / staff platform engineer, where side projects ARE the work history
- The user is early-career (no employment history to anchor the skills)
- The personal project is the user's primary income source (freelance, indie hacker, founder)

Default off, exception on, never the other way around.

## Related Skills

- `task-resilience` — for the safe-edit discipline (insert-only, preserve original, write to new file). Load `external-audience-writing` to know WHAT to write, load `task-resilience` for HOW to edit safely.
- `task-resilience/references/cv-and-document-redlines.md` — the file-surgery mechanics (zip manipulation, XML editing, paragraph anchoring). Companion to `references/cv-redline-workflow.md` in this skill.
- `references/cv-redline-workflow.md` — the audience-first decision sequence (pick canonical → diagnose gap → greenlight → sprinkle vs section → drop weak subsections → translate vocabulary → edit → verify → bounded-change report).
- `humanizer` — for stripping AI-isms from prose. Load both when polishing AI-drafted text for human readers.

## Quick checklist before shipping any external-audience document

- [ ] Every proper noun and acronym passes the "2-second recognition" test
- [ ] Project names are translated to skill descriptions or dropped entirely
- [ ] Tech names that ARE industry-standard (HMAC, K8s, Terraform, Python, etc.) are kept
- [ ] Numbers (test counts, LOC, services, %) survive
- [ ] The first 50 words can be skim-read and still tell the audience what the writer does
- [ ] The voice is the user's, not yours (if editing an existing document)
- [ ] The original document is preserved byte-identical (if redlining)
