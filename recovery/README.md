# Hermes Estate — Disaster Recovery Runbook

**Goal:** the whole estate (code + state + services, including the hermes agents) is
automatically backed up off-machine and rebuildable on a fresh Mac with **one command**,
and that recovery is **proven** (not assumed).

**Last proven:** 2026-06-20 — full restore from GitHub into a scratch dir, `verify-restore.sh`
reported ALL CHECKS PASSED (incl. the agent importing from a freshly-built venv).

---

## What is backed up, where, and how often

| Asset | Backup location (PRIVATE) | Mechanism | Cadence |
|---|---|---|---|
| Parent config, `scripts/`, `recovery/` | `github.com/chidionyema/hermes-config` | `scripts/auto-push.sh` (`git add -A` + push) | hourly (gateway cron `hermes-config-auto-push`) |
| **`coordinator.db`** — estate state (tasks/missions/telemetry/meta) | same repo (it is tracked) | same hourly push | hourly |
| **Agent code** (`hermes-agent/`, incl. the gateway) | `github.com/chidionyema/hermes-agent` branch `estate-snapshot` | `recovery/backup-submodule.sh` (parentless snapshot, force-push) | hourly (called by `auto-push.sh`) |
| launchd service defs | `recovery/launchd/*.plist` (in config repo) | committed, API keys redacted to `__ROTATE_ME__` | on change |
| Python deps | `recovery/requirements-frozen.txt` (136 pkgs) | committed | on change |

**NOT backed up (by design):** `.env` secrets. They are re-entered + **rotated** on recovery.
The agent submodule's `origin` is the PUBLIC `NousResearch/hermes-agent`; **never push estate
code there.** The local submodule is a shallow clone, which is why we snapshot (parentless
commit) instead of a normal history push.

---

## Recover on a fresh Mac (one command)

Prereqs: `git`, `gh` authed to GitHub (`gh auth login`) for the private repos, `python3.11`,
and ideally `uv`.

```bash
# 1. get the restore script (or clone the config repo first and run it from there)
curl -fsSL https://raw.githubusercontent.com/chidionyema/hermes-config/main/recovery/restore.sh -o /tmp/restore.sh
# 2. rebuild the estate into ~/.hermes
bash /tmp/restore.sh ~/.hermes --yes
# 3. fill in secrets (and ROTATE any reused key)
$EDITOR ~/.hermes/.env
# 4. prove it
bash ~/.hermes/recovery/verify-restore.sh ~/.hermes
# 5. load services (review the __ROTATE_ME__ placeholders in the plists first)
$EDITOR ~/Library/LaunchAgents/ai.hermes.gateway.plist   # replace placeholder, then:
launchctl load -w ~/Library/LaunchAgents/ai.hermes.gateway.plist
launchctl load -w ~/Library/LaunchAgents/ai.hermes.coordinator.plist
```

`restore.sh` clones both repos, rebuilds the venv from the frozen lock, installs the
pre-commit hooks (compile gate + lane guard), stages the launchd plists, and writes a `.env`
template. It is idempotent. Flags: `--skip-venv`, `--skip-launchd`, `--yes`.

---

## Verify a backup/restore at any time (no fresh machine needed)

```bash
rm -rf /tmp/estate-restore-test
bash ~/.hermes/recovery/restore.sh /tmp/estate-restore-test --yes   # safe: won't touch launchd
bash ~/.hermes/recovery/verify-restore.sh /tmp/estate-restore-test  # exits non-zero on any failure
rm -rf /tmp/estate-restore-test
```

`verify-restore.sh` checks: both repos present, `coordinator.db` opens with all core tables,
`telegram.py` + `coordinator.py` compile, the agent imports from the restored venv, hooks
installed, plists lint, frozen deps present. **Run this monthly (or after big changes) to keep
recovery honest.**

---

## Notes / gotchas
- The coordinator daemon runs under **system python 3.14**; the agent venv is **3.11**. Restore
  rebuilds the 3.11 venv; the daemon just needs system python on PATH.
- To recover full submodule git *history* (not just content): clone `NousResearch/hermes-agent`,
  `git fetch --unshallow`, then re-apply the `estate-snapshot` content.
- The hourly submodule snapshot is force-pushed to a single rolling branch (`estate-snapshot`);
  dated historical snapshots can also exist (e.g. `backup-2026-06-20`).
