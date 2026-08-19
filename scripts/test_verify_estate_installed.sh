#!/bin/bash
# Tests the INSTALLED section of verify_estate.sh.
#
# Run: bash ~/.hermes/scripts/test_verify_estate_installed.sh
#
# Why this file exists
# --------------------
# The section grades jobs that are installed on disk but NOT running. It exists because
# com.prospector.offsite-backup was disabled in launchctl's override database on 2026-08-17
# and nothing noticed for two days: a disabled job has no exit code, and every other check in
# the probe grades exit codes.
#
# The fault it was written for has since been repaired, so the section cannot go red against
# the live machine any more. That is exactly why the proof has to live here — a check whose
# only evidence was "it was red once" stops being evidence the moment someone fixes the thing.
#
# Both directions are asserted:
#   - too strict -> every deliberately-off job reads as a fault, the section is permanently
#     red, and nobody reads it. Seven jobs on this estate are off ON PURPOSE.
#   - too lax    -> the original regression returns.
#
# The code under test is EXTRACTED FROM THE REAL SCRIPT by marker, never copied here. The
# extraction is asserted: if the markers move, this aborts instead of testing an empty string
# and reporting success (memory: a-mutation-check-that-never-mutated).
set -uo pipefail
SRC="${1:-$HOME/.hermes/scripts/verify_estate.sh}"

SECTION="$(awk '
  /^echo "INSTALLED / { on = 1 }
  on { print }
  on && /verify_estate_fail/ && /FAIL=1/ { exit }
' "$SRC")"

for anchor in '_ALLOW=' 'print-disabled' 'plutil -extract Label' 'nothing declares why' 'on purpose'; do
  case "$SECTION" in
    *"$anchor"*) ;;
    *) echo "ABORT: extraction from $SRC lost the '$anchor' anchor — the section moved."
       echo "       Fix the awk markers above; do NOT ship a green run from this."
       exit 2 ;;
  esac
done

pass=0; fail=0

# A real fake home: real plist files, read by the real plutil. Only launchctl is stubbed,
# because launchctl is the thing we cannot ask to lie about a machine we do not own.
run() { # run <labels-on-disk-space-sep> <loaded-labels-space-sep> <disabled-labels-space-sep> <allow-tsv-body>
  TMPHOME="$(mktemp -d)"
  mkdir -p "$TMPHOME/Library/LaunchAgents" "$TMPHOME/hermes/config"
  for l in $1; do
    printf '%s\n' \
      '<?xml version="1.0" encoding="UTF-8"?>' \
      '<plist version="1.0"><dict><key>Label</key><string>'"$l"'</string></dict></plist>' \
      > "$TMPHOME/Library/LaunchAgents/$l.plist"
  done
  printf '%b' "$4" > "$TMPHOME/hermes/config/launchd_offline_allowed.tsv"

  OUT="$(
    HOME="$TMPHOME" HERMES="$TMPHOME/hermes" LOADED="$2" DISABLED="$3" bash -c '
      launchctl() {
        if [ "$1" = "print-disabled" ]; then
          for d in $DISABLED; do printf "\t\"%s\" => disabled\n" "$d"; done
          return 0
        fi
        # print gui/<uid>/<label>
        want="${2##*/}"
        for l in $LOADED; do [ "$l" = "$want" ] && return 0; done
        return 113
      }
      FAIL=0
      '"$SECTION"'
      echo "__FAIL=$FAIL"
    '
  )"
  V="$(printf '%s' "$OUT" | sed -n 's/.*__FAIL=\(.*\)/\1/p' | tail -1)"
  [ "$V" = "1" ] && V=FAIL || V=OK
  rm -rf "$TMPHOME"
}
check() { # check <name> <expected substring> <FAIL|OK>
  if printf '%s' "$OUT" | grep -qF "$2" && [ "$V" = "$3" ]; then
    echo "  PASS  $1"; pass=$((pass+1))
  else
    echo "  FAIL  $1"; printf '%s\n' "$OUT" | sed 's/^/        /'
    echo "        verdict=$V want=$3   wanted substring: $2"; fail=$((fail+1))
  fi
}

echo "INSTALLED section"

# 1. THE REGRESSION ITSELF. offsite-backup disabled, nothing declares it. This is the exact
#    machine state of 2026-08-17 to 2026-08-19, and the section must go red on it.
run "com.prospector.offsite-backup" "" "com.prospector.offsite-backup" "# nothing declared\n"
check "a disabled job with no declaration is a fault" \
      "❌ com.prospector.offsite-backup is DISABLED" FAIL

# 2. Same job, same disabled state, now declared. Must go green — otherwise the seven jobs
#    that are off on purpose make this section permanently red.
run "com.prospector.offsite-backup" "" "com.prospector.offsite-backup" \
    "com.prospector.offsite-backup\tRetired, backups moved to CI.\n"
check "a disabled job WITH a declaration is not a fault" \
      "🟡 com.prospector.offsite-backup is DISABLED" OK

# 3. Installed but never bootstrapped is the other way to be silently off, and it is NOT the
#    same as disabled — launchctl reports it in neither place.
run "ai.hermes.cockpit" "" "" "# nothing declared\n"
check "installed but never loaded is a fault" \
      "❌ ai.hermes.cockpit is installed but never loaded" FAIL

# 4. Loaded and enabled: silent, no line at all. A section that narrates its healthy jobs
#    buries the one that is not.
run "com.prospector.backup" "com.prospector.backup" "" "# nothing declared\n"
check "a loaded, enabled job is not reported" "1 estate-owned plists on disk, 0 of them" OK

# 5. A label with an empty reason column. Someone typed the name into the file and stopped.
#    That is not a decision, and accepting it would let a one-word edit silence any job.
run "com.prospector.offsite-backup" "" "com.prospector.offsite-backup" \
    "com.prospector.offsite-backup\t\n"
check "a declaration with no reason does not count" \
      "❌ com.prospector.offsite-backup is DISABLED" FAIL

# 6. A commented-out declaration must not count either — the same one-word silencing, but
#    written in a way that reads as removed.
run "com.prospector.offsite-backup" "" "com.prospector.offsite-backup" \
    "#com.prospector.offsite-backup\tRetired.\n"
check "a commented-out declaration does not count" \
      "❌ com.prospector.offsite-backup is DISABLED" FAIL

# 7. Third-party and Apple jobs are not ours to grade. A red for someone else's agent is a
#    red nobody can clear.
run "com.docker.helper" "" "com.docker.helper" "# nothing declared\n"
check "a job outside the estate namespaces is ignored" "0 estate-owned plists on disk" OK

# 8. Mixed: one declared, one not. The declared one must not mask the undeclared one.
run "com.prospector.scheduler com.prospector.offsite-backup" "" \
    "com.prospector.scheduler com.prospector.offsite-backup" \
    "com.prospector.scheduler\tMoved to Fly.\n"
check "one declared job does not mask an undeclared one" \
      "❌ com.prospector.offsite-backup is DISABLED" FAIL

# 9. Loaded AND disabled at the same time. These are two separate switches in launchd — the
#    override database says "never start this", the bootstrap says "this label exists" — and a
#    job can be in both states at once. Grading only the not-loaded case would let exactly that
#    combination through, which is what the section was written to catch.
run "com.prospector.offsite-backup" "com.prospector.offsite-backup" \
    "com.prospector.offsite-backup" "# nothing declared\n"
check "loaded but disabled is still a fault" \
      "❌ com.prospector.offsite-backup is DISABLED" FAIL

echo
echo "  $pass passed, $fail failed"
[ "$fail" -eq 0 ]
