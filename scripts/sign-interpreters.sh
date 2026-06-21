#!/bin/sh
# sign-interpreters.sh — ad-hoc codesign the Python interpreters the estate runs under launchd.
#
# WHY: macOS (TCC) persists privacy grants against a binary's code-signature identity (cdhash).
# uv/standalone CPython and some Homebrew builds ship COMPLETELY UNSIGNED, so every launch looks
# like a brand-new unknown app — macOS re-prompts ("Python wants to access data from other apps")
# even after you click Allow, because there is no stable identity to attach the grant to.
# An ad-hoc signature gives the binary a stable cdhash, so a single Allow (or a Full Disk Access
# grant) finally sticks.
#
# Re-run this after ANY Python upgrade that moves/replaces the interpreter
# (e.g. `uv python upgrade`, `brew upgrade python`) — the new binary will be unsigned again.
set -eu

resolve() { /usr/bin/python3 -c 'import os,sys;print(os.path.realpath(sys.argv[1]))' "$1" 2>/dev/null || true; }

# The interpreters that run under launchd or get spawned by the estate and hit TCC.
INTERPRETERS="
$HOME/.hermes/hermes-agent/venv/bin/python
/usr/local/bin/python3
"

for p in $INTERPRETERS; do
  [ -e "$p" ] || continue
  real=$(resolve "$p")
  [ -n "$real" ] && [ -e "$real" ] || continue
  if /usr/bin/codesign -dv "$real" >/dev/null 2>&1; then
    echo "✓ already signed: $real"
  elif [ -w "$real" ]; then
    /usr/bin/codesign --force --sign - --timestamp=none "$real" && echo "✅ ad-hoc signed: $real"
  else
    echo "⚠️ unsigned but not writable (re-run with sudo): $real"
  fi
done

echo "Done. If macOS still prompts: grant Full Disk Access to the resolved binary above"
echo "(System Settings ▸ Privacy & Security ▸ Full Disk Access ▸ + ▸ Cmd-Shift-G ▸ paste path),"
echo "then restart the daemons:  launchctl kickstart -k gui/\$(id -u)/ai.hermes.gateway"
