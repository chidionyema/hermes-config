#!/usr/bin/env bash
# Everything that must be true before any Hermes job starts.
set -euo pipefail

# State lives on the volume, never in the image. These are the directories the laptop
# jobs assume exist; launchd created them years ago and nobody has thought about them
# since, which is exactly why a fresh container fails on the first write.
for d in logs state runs receipts; do
  mkdir -p "/data/$d"
  ln -sfn "/data/$d" "/Users/chidionyema/.hermes/$d"
done

# THE DATABASES ARE NOT INSIDE state/. They sit at the root of ~/.hermes: state.db is 129 MB
# and coordinator.db is 33 MB on the laptop, while state/state.db is a 0-byte file left over
# from July. Linking the four directories above therefore put no database on the volume at
# all, and the container wrote its real work to the image filesystem, which a deploy throws
# away.
#
# Two things are fixed here, both measured on prospector-hermes at 09:40 on 2026-08-18.
# First, an orphan sidecar: .dockerignore said `*.db`, which does not match `state.db-wal`,
# so the image carried a 1.9 MB write-ahead log with no database behind it. SQLite opening
# that pair cannot tell you what is missing, so the sidecar is deleted before it is seen.
# Second, the link itself. Both the database and its -wal/-shm are linked, because SQLite
# picks that pair of paths from the name it was handed and it is not worth depending on
# whether it resolves the symlink first: either way both ends land in /data/db.
mkdir -p /data/db
for db in state.db coordinator.db kanban.db; do
  for f in "$db" "$db-wal" "$db-shm"; do
    p="/Users/chidionyema/.hermes/$f"
    # A real file here came from the image, never from the volume. Only the database itself
    # is worth keeping, and only when the volume has nothing yet.
    if [ -f "$p" ] && [ ! -L "$p" ]; then
      case "$f" in
        *-wal|*-shm) rm -f "$p" ;;
        *) [ -s "/data/db/$f" ] || cp "$p" "/data/db/$f"; rm -f "$p" ;;
      esac
    fi
    ln -sfn "/data/db/$f" "$p"
  done
done
echo "entrypoint: databases linked to /data/db ($(ls -1 /data/db 2>/dev/null | wc -l | tr -d ' ') files on the volume)" >&2

# ROUTE OFF claude-cli IN THIS CONTAINER. Every role's chain leads with or falls back to
# `claude -p`, and this image has no node and no Claude Code: `command -v claude` answers
# nothing. A chain whose head cannot run is the 92,292-RouteExhausted bug route.py was
# rewritten to make impossible - the call still "succeeds" via the fallback, so nobody sees
# that a guaranteed failure is paid first.
#
# So the container declares its own routing rather than inheriting the laptop's. MiniMax is
# an HTTP transport with MINIMAX_API_KEY, which is already one of this app's secrets, so this
# needs no Anthropic credits and no subscription - both of which the founder has ruled out.
#
# This file is written at boot and is NOT in the repo: on the laptop `claude` exists and leads
# the chain, and committing a routing.json would silently re-point that too.
cat > /Users/chidionyema/.hermes/routing.json <<'ROUTING'
{
  "coordinator": [["minimax", "MiniMax-M3"]],
  "strategist":  [["minimax", "MiniMax-M3"]],
  "executor":    [["minimax", "MiniMax-M3"]]
}
ROUTING
echo "entrypoint: routed coordinator/strategist/executor to minimax (no claude CLI here)" >&2

# MAKE ~/.hermes/.env EXIST. Eight scripts read it as a file; on Fly the same values are
# environment variables. Without this, otto-server dies on FileNotFoundError at import time
# and supervisor parks it in FATAL, while every other program starts - so the container looks
# healthy from the outside. See deploy/hermes/env.keys for what goes in and why it is a
# declared list rather than a dump of the environment.
#
# Written to the image filesystem, never to /data: a secret belongs in neither a layer nor a
# volume snapshot. It is rebuilt from the environment on every boot.
ENV_KEYS=/Users/chidionyema/.hermes/deploy/hermes/env.keys
ENV_FILE=/Users/chidionyema/.hermes/.env
if [ -f "$ENV_KEYS" ]; then
  umask 077
  : > "$ENV_FILE"
  written=0
  while read -r k; do
    case "$k" in ''|'#'*) continue ;; esac
    # Indirect expansion, so an unset key is skipped rather than written as an empty string -
    # an empty TELEGRAM_BOT_TOKEN reads as "configured" to every script that tests for presence.
    if [ -n "${!k:-}" ]; then
      printf '%s=%s\n' "$k" "${!k}" >> "$ENV_FILE"
      written=$((written + 1))
    fi
  done < "$ENV_KEYS"
  # Count only. Never the names, and never the values.
  echo "entrypoint: wrote $written secrets into $ENV_FILE" >&2
fi

# THE DOUBLE-ANSWER FENCE. The Telegram gateway is a long poller. Two of them against
# one bot token means every message is answered twice, and Telegram hands each update
# to whichever process asked first, so the two disagree at random. While the laptop
# gateway is still running, this one must not start. It is `autostart=false` in
# supervisord and is started deliberately, after the laptop's is stopped:
#
#   fly ssh console -a hermes -C "supervisorctl start gateway"
#
# This line only reports the state, because refusing to boot the whole container over
# it would take the coordinator and cockpit down with it.
if [ "${HERMES_GATEWAY_AUTOSTART:-0}" = "1" ]; then
  echo "entrypoint: gateway WILL autostart - make sure the laptop gateway is stopped" >&2
else
  echo "entrypoint: gateway is held back; start it with 'supervisorctl start gateway'" >&2
fi

exec "$@"
