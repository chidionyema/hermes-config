# Always-on estate (Mac host)

## Layer 1 — Mac keep-awake

`ai.hermes.keepawake` runs `/usr/bin/caffeinate -dims` via LaunchAgent (`KeepAlive` + `RunAtLoad`). Logs: `~/.hermes/logs/keepawake.{out,err}.log`.

This is **layer 1 only**: it asserts the Mac stays awake while the session/agent is loaded. It is not cloud HA.

## Mac sleep still kills the estate

Lid close, battery, Low Power Mode, thermal pressure, logout, or Energy Saver still sleeping the machine will stop gateway, coordinator, and local agents. Keep-awake does not survive a full sleep/power-off.

## Cloud verdict — recommend hybrid door

Prefer **gateway + coordinator on a small VPS** as the always-reachable door; Mac stays an optional worker/dev host. Pure Mac-only always-on is fragile for founder travel and sleep. Hybrid: cloud front door, Mac for heavy local tools when awake.

## Evening migrate checklist (5 steps)

1. Snapshot/export `~/.hermes` secrets + `config.yaml` (no commit of secrets).
2. Provision VPS; install Hermes gateway + coordinator; point DNS/Telegram webhook.
3. Smoke: coordinator tick + gateway alive from phone while Mac sleeps.
4. Point Mac LaunchAgents to optional/worker mode; keep keepawake for when Mac is docked.
5. Document rollback: Mac-local plist labels + how to re-bootstrap.

## Founder Energy Saver tip

In **System Settings → Energy** (or Battery → Options): enable **Prevent automatic sleeping when the display is off** / prevent sleep on power adapter. Optional (sudo, one-time): `sudo pmset -c sleep 0 disksleep 0`. Display may sleep; host should stay up on AC. Lid/battery still override.
