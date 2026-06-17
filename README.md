# hermes-config

Hermes agent configuration — skills, memories, config, and prompts.

## Structure

```
hermes-config/
├── config.yaml          # Hermes configuration (strip secrets before commit)
├── skills/              # All agent skills (working knowledge)
│   ├── lux-proof-driven-development/
│   ├── popdd-inline-attestation/
│   └── ...
├── memories/            # Persistent agent memory
│   ├── MEMORY.md        # Project facts, lessons, contracts
│   └── USER.md          # User preferences and behavior rules
├── hooks/               # Hermes event hooks
└── cron/                # Scheduled job configs (not output)
```

## Usage

Pull latest before each session:
```bash
cd ~/.hermes && git pull
```

Push after any skill/memory update:
```bash
cd ~/.hermes && git add -A && git commit -m "..." && git push
```

Or set up the auto-push cron (recommended).

## What NOT to commit

Run `cat .gitignore` — this is handled automatically.
