# macOS-specific Hermes discovery

## LaunchAgent
Hermes runs as a **macOS LaunchAgent** managed by `launchd`. Check with:
```bash
launchctl list | grep hermes
```

The plist lives at:
```
~/Library/LaunchAgents/ai.hermes.gateway.plist
```

Key properties:
- **Auto-start:** RunAtLoad=true, KeepAlive=true
- **Executable:** `~/.hermes/hermes-agent/venv/bin/python -m hermes_cli.main gateway run --replace`
- **Stdout:** `~/.hermes/logs/gateway.log`
- **Stderr:** `~/.hermes/logs/gateway.error.log`

No crontab, no tmux, no shell aliases, no pm2 — launchd is the sole entrypoint.
