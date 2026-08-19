#!/usr/bin/env bash
# Proves check_single_environment.sh can actually fail. A guard nobody has seen fail is a
# guard nobody has tested. launchctl is stubbed on PATH so the test needs no real daemon.
set -uo pipefail
HERMES="${HERMES_HOME:-$HOME/.hermes}"
CHECK="$HERMES/scripts/check_single_environment.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
rc_all=0
note(){ printf '%s %s\n' "$1" "$2"; }

mkstub(){ printf '#!/bin/sh\ncat <<'"'"'OUT'"'"'\n%s\nOUT\n' "$1" > "$TMP/launchctl"; chmod +x "$TMP/launchctl"; }

# 1. Two environments -> exit 1.
mkstub '1713	0	ai.hermes.keepawake
62935	-15	ai.hermes.coordinator'
PATH="$TMP:$PATH" "$CHECK" >"$TMP/out1" 2>&1; rc=$?
if [ "$rc" -eq 1 ] && grep -q 'two environments' "$TMP/out1"; then
  note "ok  " "a loaded ai.hermes.coordinator fails the check"
else
  note "FAIL" "expected exit 1 and 'two environments', got exit $rc"; cat "$TMP/out1"; rc_all=1
fi

# 2. Only Mac-local daemons -> exit 0.
mkstub '1713	0	ai.hermes.keepawake
1705	0	ai.hermes.idle-engine
98750	0	ai.hermes.gateway'
PATH="$TMP:$PATH" "$CHECK" >"$TMP/out2" 2>&1; rc=$?
if [ "$rc" -eq 0 ]; then
  note "ok  " "keepawake, idle-engine and the gateway do not trip it"
else
  note "FAIL" "expected exit 0, got $rc"; cat "$TMP/out2"; rc_all=1
fi

# 3. The gateway is deliberately NOT fenced by this check — it has its own fence.
if grep -q 'gateway' <<<"$(sed -n '/^DUPLICATED=/p' "$CHECK")"; then
  note "FAIL" "gateway must not be in DUPLICATED; HERMES_GATEWAY_AUTOSTART fences it"; rc_all=1
else
  note "ok  " "gateway is excluded from DUPLICATED on purpose"
fi

# 4. Declaring the Mac primary turns the fence off rather than lying about it.
mkstub '62935	-15	ai.hermes.coordinator'
HOMECFG="$TMP/hermes"; mkdir -p "$HOMECFG/config" "$HOMECFG/scripts"
cp "$CHECK" "$HOMECFG/scripts/"; echo mac > "$HOMECFG/config/primary_environment"
PATH="$TMP:$PATH" HERMES_HOME="$HOMECFG" "$HOMECFG/scripts/check_single_environment.sh" >"$TMP/out4" 2>&1; rc=$?
if [ "$rc" -eq 0 ] && grep -q 'declared primary' "$TMP/out4"; then
  note "ok  " "primary_environment=mac makes the laptop legal"
else
  note "FAIL" "expected exit 0 with mac primary, got $rc"; cat "$TMP/out4"; rc_all=1
fi

[ "$rc_all" = 0 ] && echo "GATE: PASS" || echo "GATE: FAIL"
exit $rc_all
