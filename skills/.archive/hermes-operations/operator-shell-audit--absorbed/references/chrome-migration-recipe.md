# Chrome Migration Recipe — `nav()` → `with_nav()`

Mechanical pass to convert every panel from raw `nav(...)` calls to the
canonical `with_nav(...)` wrapper. One commit, one PR.

## Why

`panel_chrome.py` exports both:

- `nav(...)` — low-level helper that emits the nav row.
- `with_nav(...)` — the canonical wrapper. Composes `compose → nav → clip → footer → header` in one call. This is the version every panel should use.

22 of 22 panels that import `panel_chrome` reach for `nav(...)` directly. None use `with_nav(...)`. Result: nav footer ordering, footer placement, and tap patterns drift across panels.

## Migration steps

For each panel listed in the audit:

1. **Replace** `from .panel_chrome import nav` with `from .panel_chrome import with_nav` (keep any other imports).
2. **Replace** the return statement that calls `nav(body, ...)` with `return await with_nav(body, section=<panel_name>, ctx=ctx)`.
3. **Render function must be `async def`** — `with_nav` is async. If the existing render is sync, wrap: `return await with_nav(...)`.
4. **Test** — render the panel end-to-end and confirm the nav footer appears once and at the bottom.

## Canonical pre/post

**Before:**

```python
from .panel_chrome import nav

def render_X(ctx):
    body = compose_X(ctx)
    return nav(body, ctx=ctx, children=["status", "diff"])
```

**After:**

```python
from .panel_chrome import with_nav

async def render_X(ctx):
    body = compose_X(ctx)
    return await with_nav(body, section="X", ctx=ctx)
```

## Edge cases

### Panel that emits its own bespoke nav row

Some panels (e.g. `cockpit`) hand-roll a richer nav row with toggle buttons.
The canonical `with_nav` wraps *one* nav row at the bottom. For richer
rows:

- Either accept the canonical row and put toggles *above* it.
- Or document the panel as `chrome: bespoke` and skip migration.

### Panel that doesn't render a panel at all (e.g., `delivery.py` orchestrator)

Skip migration — there's no body to wrap. The audit will show these naturally.

### Async signature change breaks callers

Every caller of `render_X` needs to `await` it now. Run the smoke test
before committing.

## Verification

Re-run the chrome axis of the audit script. Every panel with `imports_chrome=True` should also have `with_nav=True`. Flag column should read ✅ for every panel.

If `delivery.py` or `cron_ops.py` legitimately skip chrome, add their names to the audit's exclusion list with a comment explaining why.
