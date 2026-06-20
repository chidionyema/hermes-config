# Estate disaster recovery (rebuild on a fresh Mac)

Everything needed to bring the estate back, in order. Secrets are NOT here (by design) —
re-enter / rotate them.

1. **Clone the config repo** (this parent):
   `git clone https://github.com/chidionyema/hermes-config.git ~/.hermes`
   — brings the parent code, `scripts/`, and `coordinator.db` (tasks/missions/telemetry/memory).

2. **Restore the submodule code** from the private snapshot (the live clone was shallow):
   `cd ~/.hermes && git clone -b backup-2026-06-20 https://github.com/chidionyema/hermes-agent.git hermes-agent`
   — content-complete (incl. the telegram crash-loop fix). For full history instead:
   clone `NousResearch/hermes-agent` then re-apply customizations from the snapshot.

3. **Recreate the venv:** `cd hermes-agent && python3.11 -m venv venv && venv/bin/pip install -r requirements*.txt`

4. **Re-enter secrets** into `~/.hermes/.env` (NOT in git): `TELEGRAM_BOT_TOKEN`,
   `TELEGRAM_HOME_CHANNEL`, `TELEGRAM_ALLOWED_USERS`, model API keys. ROTATE any old key.

5. **Reinstall pre-commit hooks** in both repos:
   `cp ~/.hermes/scripts/git-pre-commit-hook.sh ~/.hermes/.git/hooks/pre-commit && chmod +x` (same for the submodule).

6. **Install launchd services:** copy `recovery/launchd/*.plist` to `~/Library/LaunchAgents/`,
   replace the `__ROTATE_ME__*` placeholders with real (rotated) values, then
   `launchctl load -w ~/Library/LaunchAgents/ai.hermes.gateway.plist` (and the coordinator).

That's the whole estate back: code + state + services. Only secrets are re-keyed by hand.
