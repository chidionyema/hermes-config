---
name: apple-productivity
description: "Use macOS and Apple apps for synced notes, reminders, messages, Find My tracking, and desktop automation."
version: 1.0.0
author: Hermes Agent
platforms: [macos]
metadata:
  hermes:
    tags: [apple, macos, notes, reminders, imessage, findmy, automation]
---

# Apple Productivity and macOS Automation

Use this class skill for Apple-native personal productivity and desktop interaction.

## Notes and reminders
- Apple Notes: use `memo` for create/search/edit/export; prefer it when iCloud sync is desired.
- Apple Reminders: use `remindctl`; clarify Apple Reminders versus an agent cron alert, and confirm content/date before creating.
- Use JSON output for programmatic parsing and verify due date separately from alarm/notification time.

## Messages
- Use `imsg` for iMessage/SMS history and sending.
- Confirm recipient and exact message before sending; verify attachments and never bulk-message.

## Find My
- Find My has no stable CLI/API; use AppleScript/UI automation and screenshots, then inspect the screenshot.
- Keep privacy and ownership boundaries explicit; AirTag updates require the relevant view to remain active.

## Desktop automation
- Capture the app/UI first, prefer accessibility element indices over coordinates, and recapture after state changes.
- Use background-safe automation without raising windows or stealing focus unless requested.
- Verify permissions, app identity, and actual post-action state.

## Safety
Mutating actions require clear target and scope. Read-only inspection can proceed, but do not claim success without command output or visual verification.
