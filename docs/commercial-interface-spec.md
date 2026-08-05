# Hermes Commercial Interface — Specification v1

## What exists today (working)

| Surface | What it does | How to access |
|---------|-------------|---------------|
| **Web Dashboard** | Health score (6 dims), pipeline gates, outcomes, invariants, compliance, policy status | Bookmark: `https://<tunnel>.trycloudflare.com` |
| **Telegram `/` menu** | 30 slash commands: `/panel`, `/status`, `/health`, `/help`, etc. | Type `/` in Telegram chat |
| **Telegram chat** | Send any message → Home panel with project triage + Dashboard/Health buttons | Type `hi` or any word |

## What should exist

### 1. Permanent dashboard access (zero taps to discover)

**Solution: Telegram Web App button**
- A `📱` button permanently visible next to the chat input on mobile
- Tapping it opens the web dashboard in Telegram's in-app browser
- Always there. No message required. Works even if bot is offline.
- **Requires:** Register the web app URL with @BotFather (`/setmenubutton`)

**Fallback (works today):** Bookmark the dashboard URL on phone home screen.

### 2. Self-improvement evidence — always visible

**Current:** Health data is on a separate panel. You have to tap 🧠 Health to see it.

**Should be:** The Home panel shows a 2-line summary:
```
━━━━━━━━━━━━━━━━━━━━
🧠 Learning: 69% · 14 policies · 378 injections
   Fixes: 4 · Firings: 2 · Cron: 59%
```
Tapping `🧠` opens the full Health panel with all 7 tiers of evidence.

**Status:** Code exists. Needs verification it renders correctly in Telegram.

### 3. Proactive alerts (push, don't pull)

| Trigger | Alert |
|---------|-------|
| CI fails | `🔴 Prospector CI failed` with [Fix] button |
| Credits low | `🟡 API credits low — 27 warnings` |
| Moat down | `🔴 Prospector moat down — pipeline blocked` |
| Weekly digest | `🧠 Otto learned: 14 policies, 378 injections` (Monday 9am) |

**Status:** CI watcher code exists. Not wired to push yet.

### 4. Natural language (type, don't navigate)

| You type | Bot does |
|----------|---------|
| `deploy prospector` | Triggers deploy |
| `what's broken` | Shows triage |
| `fix all` | Runs auto-fixer |
| `client tie` | Switches to client view |
| `health` | Shows health panel |

**Status:** Code exists. Needs testing on live bot.

### 5. Clean message hygiene

**Problem:** 95 pinned messages accumulated over months.

**Solution:** 
- No auto-pinning. Every response is a normal message.
- Auto-unpin-all runs once on next gateway startup.
- Only the operator explicitly pins messages if they want.

**Status:** pin_edit=False is set. Unpin-all code exists. Gateway restarted.

---

## Implementation order

### Step 1: Verify current state (5 min)
- [ ] Send `hi` to bot → confirm Home panel shows with Dashboard + Health buttons
- [ ] Type `/health` → confirm full health panel with 6 dimensions
- [ ] Open dashboard URL in browser → confirm it loads

### Step 2: BotFather setup (2 min)
- [ ] Open @BotFather in Telegram
- [ ] Send `/setmenubutton`
- [ ] Select the Otto bot
- [ ] Paste the current dashboard URL
- [ ] Enter button text: `📱 Dashboard`

### Step 3: Fix whatever breaks during Step 1 (TBD)
- [ ] If Home panel doesn't show → check gateway log
- [ ] If health panel doesn't load → check dispatch route
- [ ] If dashboard doesn't load → restart tunnel

### Step 4: Wire proactive alerts (30 min)
- [ ] Add CI watcher to gateway startup
- [ ] Push Telegram notification on CI status change
- [ ] Test by manually triggering a CI failure

### Step 5: Polish (30 min)
- [ ] Test all natural language commands
- [ ] Fix any truncated button names
- [ ] Verify weekly digest push
- [ ] Remove debug logging

---

## What we STOP doing

- ❌ Adding features without verifying current ones work
- ❌ Restarting gateway without checking what broke
- ❌ Building UI panels before confirming the API works
- ❌ Multiple overlapping solutions for the same problem
- ❌ Trial-and-error coding without a spec
