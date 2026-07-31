#!/usr/bin/env bash
# install_keepawake.sh — durable Mac-local always-on assertion for the estate host.
#
# Installs ~/Library/LaunchAgents/ai.hermes.keepawake.plist (caffeinate -dims) and
# bootstraps it. No sudo. Does NOT change pmset — founder may run those once
# (documented below) if Energy settings still allow sleep past caffeinate.
set -euo pipefail

HERMES="${HERMES_HOME:-$HOME/.hermes}"
SRC="$HERMES/recovery/launchd/ai.hermes.keepawake.plist"
DST="$HOME/Library/LaunchAgents/ai.hermes.keepawake.plist"
LABEL="ai.hermes.keepawake"
UID_N="$(id -u)"
DOMAIN="gui/${UID_N}"

mkdir -p "$HERMES/logs" "$HOME/Library/LaunchAgents"

if [[ ! -f "$SRC" ]]; then
  echo "✖ missing $SRC" >&2
  exit 1
fi

cp "$SRC" "$DST"
# Strip XML comments for launchd (some macOS versions are picky)
if command -v plutil >/dev/null 2>&1; then
  # rewrite as clean plist via python to drop comments
  python3 - <<'PY' "$DST"
import sys
from pathlib import Path
p = Path(sys.argv[1])
text = p.read_text()
# remove <!-- ... --> blocks
import re
clean = re.sub(r"<!--.*?-->", "", text, flags=re.S)
p.write_text(clean)
PY
  plutil -lint "$DST" >/dev/null
fi

# unload if already loaded (idempotent)
launchctl bootout "${DOMAIN}/${LABEL}" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$DST"
launchctl enable "${DOMAIN}/${LABEL}" 2>/dev/null || true
launchctl kickstart -k "${DOMAIN}/${LABEL}" 2>/dev/null || launchctl kickstart "${DOMAIN}/${LABEL}"

sleep 1
if launchctl print "${DOMAIN}/${LABEL}" 2>/dev/null | grep -q "state = running"; then
  echo "✔ ${LABEL} running (caffeinate -dims)"
else
  echo "⚠ ${LABEL} loaded but not yet running — check: launchctl print ${DOMAIN}/${LABEL}" >&2
  launchctl print "${DOMAIN}/${LABEL}" 2>&1 | head -30 || true
  exit 1
fi

cat <<'EOF'

Optional one-time founder steps (sudo — do NOT automate):
  # Prefer Prevent automatic sleeping on power adapter (System Settings → Energy)
  # Or, if you accept pmset:
  #   sudo pmset -c sleep 0 disksleep 0
  #   sudo pmset -c displaysleep 10   # display may sleep; host stays up
  # Lid close / battery / thermal / low-power mode can still sleep the Mac.
EOF
