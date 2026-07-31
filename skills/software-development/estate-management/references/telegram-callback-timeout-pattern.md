# Telegram Callback Timeout — Acknowledge First, Run Second

**Class of bug:** Slow async handler behind a Telegram callback query. The handler runs **before** `query.answer()` is called. The query ID expires while the handler is still working. The button tap "appears to do nothing."

**Discovered:** 2026-07-31. Bit every callback that took longer than ~15s (the Telegram Bot API callback query TTL).

## The Bug

```python
# gateway/platforms/telegram.py — BEFORE
view = await asyncio.to_thread(handle_estate_action, action, rid)
if view.toast:
    await query.answer(text=view.toast[:200])
else:
    await query.answer()

# ... then ...
edited = await query.edit_message_text(...)
```

Telegram callback queries have a ~15 second TTL. The `query.answer()` call fails with:

```
telegram.error.BadRequest: Query is too old and response timeout expired or query id is invalid
```

Worse: if `query.answer()` throws, **the surrounding code that edits the message may also fail** — because Telegram has marked the query dead. The button tap appears as "nothing happened" on the phone.

**Measured offenders in the operator_shell (live probes 2026-07-31):**

| Action | Cold time | Why slow |
|---|---|---|
| `estate:st_status` | 56.8s | Subprocess probes Stripe + runs `storeops status` |
| `estate:builds` | 8.2s | Hits GitHub Actions API |
| `estate:refresh` | 6.5s | Coordinator + daemons + 4 sqlite queries |
| `estate:st_health` | up to 126s | Stores probe — seen in activity log |
| `estate:st_money` | up to 88s | Stripe + ledger reconciliation |

Every one of these triggered the bug for the founder on a phone tap.

## The Fix (1-line)

```python
# gateway/platforms/telegram.py — AFTER
rid = str(getattr(query, "id", "") or "")
await query.answer(text="…")                       # ACK FIRST, with placeholder
view = await asyncio.to_thread(handle_estate_action, action, rid)

# ... then ...
edited = await query.edit_message_text(...)
```

**The rule:** Telegram callback queries are lease-held. Acknowledge the lease as soon as you receive it. Do the work after. The `…` toast is shown in the bubble instantly; the message edit shows the real result when ready.

## Why Acknowledge-First Works

Telegram's callback query lifecycle:

1. User taps inline button
2. Telegram sends `CallbackQuery` to your bot
3. Bot must call `answer_callback_query` within ~15s, or Telegram marks the query invalid
4. Bot can ALSO `edit_message_text` — but only if (a) the query was acknowledged first, or (b) the message was sent by the bot itself and Telegram tolerates the edit

If you run the handler before answering, you're holding the lease while doing the work. With slow handlers, the lease expires and the user sees no feedback.

## Where the Same Bug Can Appear

The pattern applies to **any async Telegram handler**, not just estate panels:

- Approval buttons (`ea:*` — `resolve_gateway_approval` can take seconds if it triggers a chain)
- Slash-confirm buttons (`sc:*`)
- Task approval buttons (`task:*`)
- Prompt approval buttons (`prompt:*`)
- Any future callback handler

**Audit checklist:** `grep -n "query.answer\|answer_callback_query" gateway/platforms/telegram.py` — for every `answer_callback_query` call site, verify it happens **before** any awaitable work.

## Defense in Depth — Loading Indicator on the Message Itself

Acknowledge-first kills the "did my tap register?" question for the toast. It does **not** kill the "is the page still old content?" question during a 60s probe. Two follow-ups worth considering:

1. **Edit the message to show a loader:** `await query.edit_message_text(text="⏳ Loading…", parse_mode=…)` between ack and the result. Replaces the now-stale card with a visible "I'm working on it" before `edit_message_text` returns with the real result.

2. **Pre-flight probe + cache:** render the panel every 30s in the background and cache the last-known result in `state.db`. On tap, return the cached version in <50ms, then kick a background refresh. The phone never blocks.

## Diagnostic — How to Find Slow Handlers

```bash
# Time every action end-to-end
python3 -c "
import sys, time
sys.path.insert(0, '~/.hermes/hermes-agent')
from gateway.operator_shell.estate import handle_estate_action
for action in ['refresh', 'run', 'tune', 'inbox', 'builds', 'st_status', 'status']:
    t0 = time.time()
    view = handle_estate_action(action)
    print(f'{action:12s}: {(time.time()-t0)*1000:6.0f}ms')
"
```

**Threshold:** anything > 3000ms is at risk on flaky networks. Anything > 10000ms will hit the bug on a slow Telegram connection.

## Related Patterns

- **Idempotency receipts** (`estate.py:_dispatch`) — every callback has a `request_id` (Telegram's callback query ID) so a replay returns the cached result. Combine with ack-first: ack-first for the first call, replay for any duplicate.
- **Inline exception in PanelView, not raise** — when the handler does fail, return a `PanelView(text="⚠️ …", ok=False)` instead of throwing. The render layer logs the failure but the message still edits, so the user sees an error card, not nothing.
- **Pre-flight probe** — see the spec idea #2 ("Living progress message") and the proposal for state.db-cached panel snapshots.

## Pitfall: Don't Add the Ack Wait for the Result

A wrong fix is to wait for the result before answering:

```python
# WRONG — same bug, different shape
result = await asyncio.to_thread(slow_handler)
await query.answer(text=result.toast or "done")  # query may be expired
```

This is identical to the broken code. The ack must come **first**, not "as soon as the result is ready". Telegram does not care about your result.

## Pitfall: `query.answer()` Without a Toast Succeeds Silently

`await query.answer()` (no `text=` argument) just dismisses the toast. The user sees nothing. For slow handlers, pass `text="…"` (literally three dots, or "Loading…") so the toast shows the user their tap landed.

## Carry-Over Tracking

| Date | Finding | Status |
|---|---|---|
| 2026-07-31 | Discovered in operator_shell callback — 5 actions over 3s, 3 over 15s | **fixed, verified live** |
