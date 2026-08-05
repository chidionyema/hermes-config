# Hermes Agent UI/UX Polish

## Goal
Make the Hermes agent's Telegram UI (commercial_ui.py) and web dashboard (health_panel.py) "ultra premium" — bleeding-edge, seamless, ultra-thoughtful. Polished to the same standard as Linear, Stripe, or Vercel's interfaces.

## Files to improve
- `gateway/operator_shell/commercial_ui.py` — Telegram UI module (keyboards, buttons, messages)
- `gateway/operator_shell/health_panel.py` — Health dashboard
- `gateway/operator_shell/discovery.py` — Discovery UI
- `gateway/operator_shell/health_panel.py` — Health card

## What "ultra premium" means
- Every response has clear visual hierarchy
- Buttons use consistent, meaningful labels
- Empty states are informative, not just blank
- Error messages explain what happened AND what to do
- No "TODO" or "placeholder" text in user-facing messages
- Markdown formatting is consistent (bold for emphasis, code for commands, emojis only where they add meaning)
- Progressive disclosure: detailed info available but not overwhelming
- Status indicators are clear (🟢 active, 🟡 pending, 🔴 error) with explanations

## What to do each iteration
1. Read `commercial_ui.py` or `health_panel.py` 
2. Find ONE specific UI element that could be better (vague copy, missing context, inconsistent formatting, poor error feedback)
3. Fix it with minimal, targeted changes
4. Run the check script: `bash ~/.hermes/specs/ui-polish-loop-check.sh`
5. Commit with `HERMES_LANE=claude git commit -m "..."`
6. Report what changed

## What NOT to do
- Don't redesign architecture
- Don't add new features
- Don't change Telegram command structure
- Don't modify configs or credentials

## Completion criteria
The check script returns SCORE: 10 (exit 0). Until then, keep iterating.
