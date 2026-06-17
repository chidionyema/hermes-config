# CV Redline Workflow — Audience-First, Section-Aware

The companion to `task-resilience/references/cv-and-document-redlines.md` (file-surgery mechanics). This file covers the **audience decisions** that come *before* the file surgery: what to insert, what to drop, how to phrase it, what reads right to a hiring manager.

Load both files together when redlining a CV. Load only this one when deciding what to put on the page.

## The Decision Sequence

A CV redline happens in this order. Skipping steps is how "honest disclosure" cop-outs sneak in.

1. **Pick the canonical file** — enumerate, compare timestamps, pick the most recent `.docx` (see task-resilience for heuristics).
2. **Read it fully** — extract every paragraph, map the structure.
3. **Diagnose the gap** — cross-reference against the user's actual recent work (shipped projects, certs, employment bullets). Produce a written gap analysis.
4. **WAIT FOR GREENLIGHT** — present the gap, the proposed insertion plan, and the "not done" list. Do not write until the user confirms.
5. **Decide sprinkle vs section** — run the "Sprinkle, Don't Section" test from SKILL.md on each new content block.
6. **Decide what to drop** — run the "Insufficient-Evidence Subsections" test on every existing subsection.
7. **Translate vocabulary** — run the "Translate, Don't Transcribe" rule from SKILL.md on every proper noun in the new content.
8. **Apply the edit** — write to a new file, preserve the original byte-identical (task-resilience mechanics).
9. **Verify** — zip integrity, paragraph count = original + inserted, original hash unchanged.
10. **Ship with "what I did NOT do"** — every redline report ends with a bounded-change list.

## The "Use Your Judgment" Reply Pattern

When the user gives a one-word answer to a multi-question prompt ("Use your judgment" after two questions, or just "2"), don't guess silently. The right pattern:

```
I'm interpreting "2" as the second option of the second question
(write to a new file, leave the original untouched).
If you meant something else, say so.

Picked the safer default: insert-only mode (keeps your voice, low risk).
Output: new file at ~/code/Chidi'sCV_v6_2026-06-17.docx.
Original is byte-identical to the source.
```

Three things happen in this reply:
1. State the interpretation (so the user can correct cheaply if wrong)
2. Pick the safer default (reversible, low blast-radius)
3. Name the move so it's auditable

The alternative — guessing silently and presenting the result as if it were the obvious interpretation — is the failure mode. The user has to read the redline output AND reverse-engineer your assumption AND tell you what was wrong. That's three round-trips when one would have done.

## The "Don't Do That Yet" Mid-Flight Correction

If the user said "do X" earlier and then mid-task says "don't do that yet," the right move:

1. **Acknowledge the steering** — "Got it, holding off on the CV work."
2. **Don't undo what's already done** — if a subagent already produced output, treat it as discarded; don't paste or reference it
3. **Ask for the new scope** — what changed? what should I do instead? is the original ask still valid or abandoned?
4. **Don't auto-substitute** — don't pivot to a related task you can infer. The steering signal is "stop guessing, ask."

Worked example from the 2026-06-17 session: user said "Ok but the manual copying is friction which we want to eliminate" → "Ok let's get it done" → I dispatched 5 subagents including "draft CV bullets" → user said "Regarding the cv don't do that yet." Right move: acknowledge, hold the CV subagent output as discarded, ask which of the other 4 to proceed with, don't fill the gap with my own CV work.

## When the User Pushes Back on Style

Three common style-correction patterns and how to respond:

| User says | What it means | Right move |
|---|---|---|
| "this is too verbose" / "stop explaining" | The artifact is too long for the audience | Cut to the shortest version that says the thing; ship a diff not a treatise |
| "what's X?" / "this is a cryptic puzzle" | The vocabulary is mine, not theirs | Translate to industry-standard terms; check every proper noun against the 2-second recognition test |
| "I don't want this section" | A judgment about what belongs in the document | Drop it without re-arguing; if I think it's needed, flag in the "not done" list, don't re-insert |
| "sprinkle, don't section" / "put it under my last role" | The placement matters more than the content | Move the content; the words can stay almost the same, the location flips the signal |

The pattern: style corrections are **audience signals**. The user is telling you what the audience reads, not what they think. Trust the read; the next draft should embed the lesson, not argue about it.

## Version Discipline

CVs go through 4-6 iterations in a single session. Each iteration creates a new file (`v3_2026-06-17.docx`, `v4_2026-06-17.docx`, etc.). Discipline:

- **Never delete a previous version** until the user explicitly accepts the latest.
- **Always build the next version from the most recent accepted one**, not from v3 every time. (Easy to get wrong when iterating fast.)
- **Name versions with both the iteration number AND the date.** `_v6_2026-06-17.docx` not `_v6.docx`. The date is what makes the file sortable.
- **The "current" file is whatever the user last greenlit**, not whatever you most recently wrote. If v6 was rejected in favour of v4, v4 is current, even though v6 is the latest on disk.
- **When in doubt about which version is "current"**, ask. Don't assume the highest number is the accepted one.

## Pitfall: Anchoring Insertions to Paragraph Indices

When the script does `if i == 48: insert_after(48)`, the index 48 is brittle — it changes with every insertion. The v3 file's "Prototyping ML models..." paragraph was at index 63, not 48 (a 15-paragraph off-by-some-insertion).

The robust pattern: **anchor by text content, not by index.** Search for a unique substring of the paragraph you want to insert after, and insert at that anchor:

```python
inserted = False
for i, p_elem in enumerate(all_paras):
    text = "".join(t.text or "" for t in p_elem.iter(f"{W}t"))
    if not inserted and "Prototyping machine learning models" in text:
        results.append(serialize(p_elem))
        for b in NEW_BULLETS:
            results.append(b)
        inserted = True
        continue
    results.append(serialize(p_elem))

if not inserted:
    raise RuntimeError("anchor not found — insertion failed")
```

The substring anchor is robust to other insertions because the paragraph text doesn't change when you add new paragraphs elsewhere. The raise-on-failure catches the case where the source file changed and the anchor text is gone.

**Anti-pattern:** hardcoding `if i == 48`. If you've inserted paragraphs earlier in the document, 48 is now a different paragraph. The script will silently insert at the wrong place.

## Pitfall: Off-By-One in REMOVE_INDICES

When removing N paragraphs at known positions, double-check by printing what's at each index before removal. The script that removed the "Selected Personal Projects" section initially had `REMOVE_INDICES = {49, 50, 51}` but the 4th project was actually at index 52 (heading + 3 projects = 4 paragraphs, indices 49-52). The third paragraph got missed, and the verify check passed because the verification was against v3 not v4.

**The defense:** after every remove/insert operation, re-read the resulting file and verify the **expected-absent** content is **actually absent**. Don't trust the count alone — counts can lie when other changes happen.

```python
# After the edit:
texts = ["".join(t.text or "" for t in p.iter(f"{W}t")) for p in new_paras]
for needle in ["Selected Personal Projects", "Signal Engine", "Prospector (Python, 2025"]:
    assert not any(needle in t for t in texts), f"FAILED to remove {needle}"
```

If the verification check is "this string should be gone," write that as an assertion, not a print.

## Related

- `task-resilience/references/cv-and-document-redlines.md` — file-surgery mechanics for `.docx`/`.pages`/`.pdf`
- `task-resilience/SKILL.md` — interruptible parallelism + fix-before-disclose rules
- SKILL.md §"The Core Rule: Translate, Don't Transcribe" — vocabulary table
- SKILL.md §"The Sprinkle, Don't Section Rule" — placement rules
