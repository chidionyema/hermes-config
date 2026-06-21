#!/bin/sh
# sign-interpreters.sh — ad-hoc codesign the Python interpreters the estate runs, so macOS stops
# re-prompting "Python wants to access data from other apps".
#
# WHY: macOS (TCC) persists a privacy grant against a binary's code-signature identity (cdhash).
# Homebrew/python.org framework builds run as an APP BUNDLE — the TCC identity is
#   .../Python.framework/Versions/X/Resources/Python.app  (Contents/MacOS/Python)
# NOT the bin/pythonX stub (which just re-execs into the app). uv standalone CPython is a plain
# bin with no .app. All of these ship UNSIGNED, so every launch is a new unknown identity and the
# grant never sticks → endless re-prompts. Ad-hoc signing gives a stable cdhash so one Allow (or a
# Full Disk Access grant) finally persists.
#
# Re-run after any Python upgrade (`brew upgrade python`, `uv python upgrade`) — the new binary is
# unsigned again. Then restart the daemons (see bottom).
set -eu

sign() { # $1 = path to .app bundle or bin
  [ -e "$1" ] || return 0
  if /usr/bin/codesign -dv "$1" >/dev/null 2>&1; then
    echo "✓ already signed: $1"
  elif /usr/bin/codesign --force --deep --sign - --timestamp=none "$1" 2>/dev/null; then
    echo "✅ signed: $1"
  else
    echo "⚠️ could not sign (perms/sudo?): $1"
  fi
}

# 1. Every framework Python.app bundle (Homebrew + python.org). THIS is what TCC sees.
for app in \
  /usr/local/Cellar/python@*/*/Frameworks/Python.framework/Versions/*/Resources/Python.app \
  /opt/homebrew/Cellar/python@*/*/Frameworks/Python.framework/Versions/*/Resources/Python.app \
  /Library/Frameworks/Python.framework/Versions/*/Resources/Python.app
do
  sign "$app"
done

# 2. uv standalone CPython (no .app — sign the bin). Resolve the estate venv's real interpreter.
uvpy=$(/usr/bin/python3 -c 'import os;print(os.path.realpath(os.path.expanduser("~/.hermes/hermes-agent/venv/bin/python")))' 2>/dev/null || true)
[ -n "$uvpy" ] && sign "$uvpy"

cat <<'EOF'

Signed. To make grants take effect:
  • Restart the daemons so live processes use the signed binaries:
      launchctl kickstart -k gui/$(id -u)/ai.hermes.gateway
      launchctl kickstart -k gui/$(id -u)/ai.hermes.coordinator
  • If macOS still prompts once after that: click Allow — it now sticks. To stop it proactively,
    add the Python.app above to System Settings ▸ Privacy & Security ▸ Full Disk Access
    (+ ▸ Cmd-Shift-G ▸ paste the .app path).
EOF
