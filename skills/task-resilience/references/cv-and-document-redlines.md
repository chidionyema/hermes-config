# CV and Document Redlines — When the User Says "Update My X"

The pattern when a user asks for help with a personal document they own (CV, resume, LinkedIn, bio, portfolio). Worked example: `Chidi'sCV.docx` redline on 2026-06-17.

## 1. Find the canonical source before writing

When a user has multiple versions of a document (e.g. `Chidi'sCV.docx`, `Chidi'sCV 2.docx`, `Chidi'sCV.pages`, `Chidi'sCV.pdf`, `Chidi'sCV 2.pages`), the first move is to find them all, then **pick one** with judgment.

**Selection heuristics, in order:**

1. **Newest modification date** — `stat -f "modified: %Sm" path` to get the timestamp. The most recent write is usually the live one.
2. **Format hint from the filename suffix** — `2`, `v3`, `new`, `latest` in the name signal "this is the revised one."
3. **Co-location with code/repos** — `~/code/Chidi'sCV 2.docx` lives next to the code it should describe; that's a strong signal of intent.
4. **PDF export in the same directory** — if a `.docx` has a sibling `.pdf` exported recently, the `.docx` is the live source and the `.pdf` is the rendering for sharing.
5. **When the user says "use your judgment"** — pick the most-recently-edited `.docx` in the user's working area. If there are ties, pick the one with the most `2/v3/new` suffix.

**Do not assume** a single canonical file exists. The user often has 2-5 variants and the question "which one?" is implicit. The skill is to enumerate, compare, and pick.

## 2. Diagnose the gap, don't write yet

After picking the canonical file, **read it fully** and cross-reference it against what the user has actually built. The deliverable here is a **gap analysis**, not a rewrite. The user wants to see:

- What's already there (keepers)
- What's missing (the undersell)
- What's stale (predates recent work)
- Where specifically to insert (paragraph indices in the docx)
- What's deliberately NOT being changed (their voice, structure)

This is a redline plan, not a finished document. **Wait for greenlight before applying.**

## 3. The redline protocol: insert-only by default

When the user gives greenlight on the gap analysis:

- **Default mode: insert-only.** Add new sections. Don't delete or rewrite existing content. The user's voice and structure stay intact.
- **Preserve the original.** Write to a new file (`Chidi'sCV_v3_2026-06-17.docx`), never patch the canonical in place. The original must remain byte-identical until the user reviews the redline.
- **Verify both sides.** `sha256` the original before and after the operation. If the original's hash changed, restore from the copy. This is the discipline that makes "preserve original" actually true.
- **Sanity check the new file.** Open it, parse it, confirm the paragraph count is `original + inserted`, and confirm every original paragraph is still present in the right order.

## 5. Disclose the boundaries: what you changed AND what you deliberately did NOT change

After shipping a redline, the reply must include a **"What I did NOT do"** section that names the plausible adjacent changes you consciously skipped, with a one-line reason for each. Pattern from the 2026-06-17 CV redline:

> **Not done (and you should know):**
> - I did NOT reformat the OSL entry or split titles across lines — that's an invasive change that needs your voice input
> - I did NOT add a BSc year — I'd be guessing (the CV doesn't show it; the file was created Sep 2024 so graduation was before that)
> - I did NOT touch the Profile paragraph text — your existing "comprehensive background" line is unchanged, and the "extensive experience in machine learning" claim is still there. That's a content decision I flagged but didn't make for you.

**Why this matters:** when you redline a user-owned document, you make dozens of micro-judgments (what to insert, where, how to phrase). Most of them are reversible, but the user can't reverse what they don't know happened. Naming the boundaries explicitly turns the redline from "trust me" into "verify these specific things." A user who reads the "not done" list and says "actually, do X" is a much better collaboration than a user who reads the redline summary, assumes the obvious adjacent changes were also made, and finds out later they weren't.

The pattern scales: every redline report should end with a **bounded-change report** — what changed, what didn't, what's a one-line ask away.

**Anti-pattern:** shipping a redline and saying "I made the changes you asked for." That's a true statement that hides the judgment calls. The user can't ask for the things they don't know you considered.

## 4. Editing `.docx` without python-docx

If `python-docx` is not installed (common — only `uv add python-docx` makes it available, and many sandboxes don't have it), you can edit the docx directly. A `.docx` is a zip file with `word/document.xml` inside. The structural recipe:

```python
import zipfile, shutil
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

src = "Chidi'sCV 2.docx"
dst = "Chidi'sCV_v3_2026-06-17.docx"

# 1. Copy first (preserves original)
shutil.copy2(src, dst)

# 2. Read the body
with zipfile.ZipFile(src) as z:
    raw = z.read("word/document.xml").decode("utf-8")
tree = ET.ElementTree(ET.fromstring(raw))
body = tree.getroot().find(f"{W}body")
all_paras = list(body.findall(f"{W}p"))

# 3. Build helper for new paragraphs that match the existing style
def make_p(text, bold=False, size_half_pt=None, italic=False):
    rpr_inner = ""
    if bold: rpr_inner += "<w:b/><w:bCs/>"
    if italic: rpr_inner += "<w:i/><w:iCs/>"
    if size_half_pt: rpr_inner += f'<w:sz w:val="{size_half_pt}"/><w:szCs w:val="{size_half_pt}"/>'
    rpr = f"<w:rPr>{rpr_inner}</w:rPr>" if rpr_inner else ""
    safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f'<w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:pPr><w:pStyle w:val="Default"/></w:pPr><w:r>{rpr}<w:t xml:space="preserve">{safe}</w:t></w:r></w:p>'

# 4. Serialize existing paragraphs + insert at chosen indices
def serialize(p_elem):
    return ET.tostring(p_elem, encoding="unicode")

new_body = []
for i, p in enumerate(all_paras):
    new_body.append(serialize(p))
    if i == 3:  # insert after paragraph 3
        for new_p in NEW_PARAGRAPHS:
            new_body.append(new_p)

# 5. Re-zip: preserve every other file in the docx, replace only document.xml
with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
    for item in zin.infolist():
        if item.filename == "word/document.xml":
            # splice in the new body content
            import re
            m_open = re.search(r"<w:body[^>]*>", raw)
            m_close = re.search(r"</w:body>", raw)
            new_doc = raw[:m_open.end()] + "".join(new_body) + raw[m_close.start():]
            zout.writestr(item, new_doc)
        else:
            zout.writestr(item, zin.read(item.filename))

# 6. Verify: zip integrity, paragraph count, original hash unchanged
import hashlib
with open(src, "rb") as f:
    orig_hash_before = hashlib.sha256(f.read()).hexdigest()
# ... do the edit ...
with open(src, "rb") as f:
    orig_hash_after = hashlib.sha256(f.read()).hexdigest()
assert orig_hash_before == orig_hash_after, "ORIGINAL CORRUPTED"

with zipfile.ZipFile(dst) as z:
    assert z.testzip() is None, "NEW FILE CORRUPT"
    new_paras = list(ET.fromstring(z.read("word/document.xml")).find(f"{W}body").findall(f"{W}p"))
    expected = len(all_paras) + len(NEW_PARAGRAPHS)
    assert len(new_paras) == expected, f"COUNT MISMATCH: {len(new_paras)} vs expected {expected}"
```

**Critical pitfalls:**

- **Don't blindly count expected paragraphs.** `body.findall(f"{W}p")` may include the `sectPr`-containing paragraph at the end. Add 1 to your expected count or print the count to verify.
- **Register namespaces.** `ET.register_namespace("w", "...")` before parsing prevents element tag corruption on serialization. Without it, you get `ns0:p` and the docx is invalid.
- **Preserve the `sectPr` at end of body.** The new XML must include it. Find it with `re.search(r"<w:sectPr.*?</w:sectPr>", orig_body, re.DOTALL)` and append it after your inserted paragraphs.
- **Use `<w:t xml:space="preserve">`** for any text with leading/trailing whitespace or multiple spaces. Without it, Word collapses whitespace and your formatting looks wrong.

## 5. Interpreting "Use your judgment"

When the user gives a one-word answer to a multi-question prompt ("Use your judgment" after being asked two questions), the safe interpretation is:

1. **Pick the safer/more conservative option** for each sub-question.
2. **State your assumptions explicitly** in the reply ("I picked the safer option: wrote to a new file, left the original untouched, because that lets you compare side-by-side without rollback risk").
3. **Make the move reversible.** Always keep the original intact so they can override.

The user is telling you to proceed, not telling you what they want. Proceed with judgment + transparency.

## Worked example: the CV redline (2026-06-17)

| Step | Action | Time | Output |
|---|---|---|---|
| 1 | `find` all `Chidi's*` files | <2s | 5 files: 3 .docx, 1 .pages, 1 .pdf |
| 2 | `stat` modification dates | <1s | Picked `Chidi'sCV 2.docx` (newest, in `~/code/`) |
| 3 | Extract `.docx` → text | 5s | 87 lines, structure mapped |
| 4 | Cross-reference against session memory | 5s | Gap list (10 items, 4 critical) |
| 5 | Present gap analysis + insertion plan | 1 reply | User greenlit ("2") |
| 6 | Read user reply: "2" (answer to "patch in place"?) | 1s | Interpreted as ambiguous → defaulted to safer (new file) |
| 7 | Edit `document.xml` directly | 10s | `Chidi'sCV_v3_2026-06-17.docx` (15,802 bytes) |
| 8 | Verify zip + paragraph count + original hash | 5s | All checks passed |
| 9 | Present summary + next-step menu | 1 reply | User decides |

Total: ~30 seconds wall-time after greenlight. Without greenlight-before-spawn discipline, this would have been a 5-minute subagent that wrote content the user couldn't steer mid-flight.

## When NOT to use this skill

- **The user explicitly asked for a rewrite** (not a redline). Then write a new file from scratch; don't preserve the original structure.
- **The user gave you the document text inline** (pasted into chat). Then skip the canonical-file selection — there is no canonical to find.
- **The change is single-line / trivial** (typo, date correction). Don't run the full redline protocol. Just patch and ship.
- **The user has a CI/test suite for the document** (rare for prose, but it happens for legal templates). Use the test as the contract, not this skill.
