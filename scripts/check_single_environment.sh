#!/usr/bin/env bash
# Hermes runs in ONE place. This check fails when it is running in two.
#
# Why this exists. On 2026-08-19 `supervisorctl status` on prospector-hermes showed
# coordinator, otto-server, cockpit, rsi, progress and submodule-backup RUNNING, and
# `launchctl list` on this Mac showed the same daemons live at the same time. They hold
# separate SQLite databases on separate machines, so "keep them in sync" was never available
# as an option — there were two estates, and every answer depended on which one you asked.
#
# The gateway is NOT in this list. Exactly one Telegram long-poller may exist, and which
# machine owns it is declared by HERMES_GATEWAY_AUTOSTART on the Fly side. That fence already
# works. Nothing fenced the rest.
#
# The primary is declared in a file, never hardcoded here, so failing over to the laptop is a
# one-line edit rather than a code change.
#   $HERMES/config/primary_environment   ->  "fly" (default) or "mac"
#
# Exit 0 = one environment. Exit 1 = two.

set -uo pipefail
HERMES="${HERMES_HOME:-$HOME/.hermes}"

# The daemons Fly's supervisord also runs. Keep this list in step with
# deploy/hermes/supervisord.conf.
DUPLICATED="coordinator otto-server cockpit rsi progress submodule-backup"

PRIMARY_FILE="$HERMES/config/primary_environment"
PRIMARY="fly"
[ -r "$PRIMARY_FILE" ] && PRIMARY="$(tr -d '[:space:]' < "$PRIMARY_FILE")"

echo "SOLO    one Hermes environment (declared primary: $PRIMARY)"

if [ "$PRIMARY" = "mac" ]; then
  echo "  ✅ this Mac is the declared primary — nothing to fence here"
  exit 0
fi

loaded=""
for name in $DUPLICATED; do
  if launchctl list 2>/dev/null | grep -q "[[:space:]]ai\.hermes\.${name}\$"; then
    loaded="$loaded ai.hermes.${name}"
  fi
done

if [ -z "$loaded" ]; then
  echo "  ✅ none of the Fly-side daemons is loaded on this Mac"
  exit 0
fi

echo "  ❌ two environments: these run on Fly AND are loaded here —$loaded"
echo "     Fix, per label:  launchctl bootout gui/\$(id -u)/<label>"
echo "                      launchctl disable gui/\$(id -u)/<label>   # survives a reboot"
echo "     Or declare this Mac primary:  echo mac > $PRIMARY_FILE"
exit 1
