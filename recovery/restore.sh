#!/bin/bash
# restore.sh — rebuild the Hermes estate from off-machine backups onto a fresh Mac.
#
#   Usage: restore.sh [TARGET_DIR] [--skip-venv] [--skip-launchd] [--yes]
#     TARGET_DIR     where to rebuild the estate (default: ~/.hermes)
#     --skip-venv    don't build the Python venv (structural restore only)
#     --skip-launchd don't install launchd services (default unless TARGET is ~/.hermes)
#     --yes          non-interactive (assume yes)
#
# Prereqs on the fresh machine: git, gh (authed to github for the PRIVATE repos) OR a
# git credential helper, python3.11, and optionally uv (faster venv). Secrets are NOT in
# git by design — you re-enter/rotate them at the end.
#
# What it restores: parent config + coordinator.db (state) from chidionyema/hermes-config,
# the agent code from the chidionyema/hermes-agent 'estate-snapshot' branch, the pre-commit
# hooks, and the launchd service defs (with __ROTATE_ME__ placeholders you must fill).
set -uo pipefail

CONFIG_REPO="https://github.com/chidionyema/hermes-config.git"
AGENT_REPO="https://github.com/chidionyema/hermes-agent.git"
AGENT_SNAPSHOT_BRANCH="estate-snapshot"

TARGET="${1:-$HOME/.hermes}"; case "$TARGET" in -*) TARGET="$HOME/.hermes";; *) [ $# -gt 0 ] && shift;; esac
SKIP_VENV=0; SKIP_LAUNCHD=0; ASSUME_YES=0
for a in "$@"; do case "$a" in
  --skip-venv) SKIP_VENV=1;; --skip-launchd) SKIP_LAUNCHD=1;; --yes|-y) ASSUME_YES=1;; esac; done
# Only touch the real LaunchAgents when restoring to the real home.
[ "$TARGET" != "$HOME/.hermes" ] && SKIP_LAUNCHD=1

say(){ printf '\033[1;36m== %s\033[0m\n' "$*"; }
warn(){ printf '\033[1;33m!! %s\033[0m\n' "$*"; }
die(){ printf '\033[1;31mXX %s\033[0m\n' "$*" >&2; exit 1; }

say "Restoring estate to: $TARGET   (skip-venv=$SKIP_VENV skip-launchd=$SKIP_LAUNCHD)"
command -v git >/dev/null || die "git not found"

# 1. Parent config repo (code + scripts + coordinator.db + recovery/) ------------------
if [ -e "$TARGET/.git" ]; then
  warn "$TARGET already a git repo — pulling instead of cloning"
  git -C "$TARGET" pull --ff-only || warn "pull failed (continuing)"
else
  [ -e "$TARGET" ] && [ -n "$(ls -A "$TARGET" 2>/dev/null)" ] && die "$TARGET exists and is not empty"
  say "Cloning config repo -> $TARGET"
  git clone "$CONFIG_REPO" "$TARGET" || die "clone $CONFIG_REPO failed (run: gh auth login)"
fi

# 2. Agent code from the private snapshot branch --------------------------------------
SUB="$TARGET/hermes-agent"
if [ -e "$SUB/.git" ]; then
  warn "$SUB already present — skipping agent clone"
else
  say "Cloning agent snapshot ($AGENT_SNAPSHOT_BRANCH) -> $SUB"
  git clone --single-branch -b "$AGENT_SNAPSHOT_BRANCH" "$AGENT_REPO" "$SUB" \
    || die "clone agent snapshot failed (run: gh auth login)"
fi

# 3. Python venv ----------------------------------------------------------------------
if [ "$SKIP_VENV" -eq 0 ]; then
  say "Building venv at $SUB/venv"
  ( cd "$SUB" || exit 1
    FROZEN="$TARGET/recovery/requirements-frozen.txt"
    if command -v uv >/dev/null; then
      uv venv --python 3.11 venv \
        && { [ -f "$FROZEN" ] && uv pip install --python venv/bin/python -r "$FROZEN" \
                              || uv pip install --python venv/bin/python . ; }
    else
      PY=$(command -v python3.11 || command -v python3) || { warn "no python3.11"; exit 1; }
      "$PY" -m venv venv && venv/bin/python -m ensurepip -U \
        && { [ -f "$FROZEN" ] && venv/bin/python -m pip install -r "$FROZEN" \
                              || venv/bin/python -m pip install . ; }
    fi ) || warn "venv build had issues — inspect $SUB/venv"
else
  warn "skipping venv build (--skip-venv)"
fi

# 4. Pre-commit hooks (compile gate + lane guard) in BOTH repos -----------------------
HOOK_SRC="$TARGET/scripts/git-pre-commit-hook.sh"
if [ -f "$HOOK_SRC" ]; then
  for repo in "$TARGET" "$SUB"; do
    if [ -d "$repo/.git" ]; then
      cp "$HOOK_SRC" "$repo/.git/hooks/pre-commit" && chmod +x "$repo/.git/hooks/pre-commit" \
        && say "installed pre-commit hook in $repo"
    fi
  done
else
  warn "hook source $HOOK_SRC missing — skipping hook install"
fi

# 5. launchd services -----------------------------------------------------------------
if [ "$SKIP_LAUNCHD" -eq 0 ]; then
  say "Installing launchd services"
  for plist in "$TARGET"/recovery/launchd/*.plist; do
    [ -f "$plist" ] || continue
    dst="$HOME/Library/LaunchAgents/$(basename "$plist")"
    cp "$plist" "$dst"
    warn "installed $(basename "$plist") — contains __ROTATE_ME__ placeholders; edit before loading:"
    grep -n "ROTATE_ME" "$dst" | sed 's/^/      /' || true
    echo "      then: launchctl load -w $dst"
  done
else
  warn "skipping launchd install (restore to real ~/.hermes to enable)"
fi

# 6. Secrets --------------------------------------------------------------------------
if [ ! -f "$TARGET/.env" ]; then
  say "Writing .env template (secrets are NOT in git — fill + ROTATE these)"
  cat > "$TARGET/.env" <<'ENVT'
# Hermes estate secrets — fill in and ROTATE any reused key.
TELEGRAM_BOT_TOKEN=
TELEGRAM_HOME_CHANNEL=
TELEGRAM_ALLOWED_USERS=
# model API keys (DeepSeek / MiniMax / etc.) as your config.yaml expects
ENVT
fi

say "Restore complete. Next: fill $TARGET/.env, then verify with: bash $TARGET/recovery/verify-restore.sh \"$TARGET\""
