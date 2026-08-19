#!/bin/bash
# Hermes critical-script test suite runner (Item 4 receipt).
#
# This directory holds TWO kinds of test file and they need two runners.
#
#   pytest files   — define test_* functions. Run by pytest.
#   script files   — do their work at module scope, print "Results: N passed, M failed",
#                    and end in sys.exit(). Run directly, as scripts.
#
# It used to run pytest over both. Pytest imports every file it collects, so collecting a
# script file RAN it, and a failure there was a collection error that aborted the whole
# session: `INTERNALERROR ... no tests ran`, exit 3. Measured 2026-08-17 — this repo had
# no working gate at all, which is why nothing the Hermes agent did was ever gated.
#
# conftest.py computes the split (a file with no top-level test_* function is a script)
# and hands it to pytest as collect_ignore. This runner then runs those same files itself,
# so neither kind is skipped and both verdicts count toward the exit code.
#
# Exit code: 0 only when pytest passed AND every script file exited 0.
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="${PYTHON:-python3}"
rc=0

echo "── pytest files ──"
"$PY" -m pytest "$DIR" -q
pytest_rc=$?
# 5 = "no tests collected". Not a failure here: it just means every file in this
# directory is currently script-style, which the loop below still covers.
if [ "$pytest_rc" -ne 0 ] && [ "$pytest_rc" -ne 5 ]; then rc=1; fi

echo
echo "── script-style files (run as scripts, not collected by pytest) ──"
SCRIPTS=$("$PY" -c "import sys; sys.path.insert(0, '$DIR'); import conftest; print('\n'.join(conftest.script_style_tests()))")
if [ -z "$SCRIPTS" ]; then
  echo "  (none)"
fi
while IFS= read -r f; do
  [ -n "$f" ] || continue
  out=$(cd "$DIR" && timeout 300 "$PY" "$f" 2>&1)
  s=$?
  line=$(printf '%s\n' "$out" | grep -a 'Results:' | tail -1)
  if [ "$s" -eq 0 ]; then
    printf '  ✅ %-40s %s\n' "$f" "${line:-exit 0}"
  else
    printf '  ❌ %-40s exit=%s %s\n' "$f" "$s" "${line:-no Results line}"
    printf '%s\n' "$out" | tail -12 | sed 's/^/       /'
    rc=1
  fi
done <<< "$SCRIPTS"

# ── bash test files under scripts/ ──
#
# There is a THIRD kind, and it was ungated until 2026-08-19. `scripts/test_verify_estate_*.sh`
# test the estate probe — the script CLAUDE.md calls "the live answer to is it working". They
# are not in tests/, so neither pytest nor the loop above ever saw them, and `rg -l
# test_verify_estate` found no caller anywhere in the repo. They were written, they passed when
# run by hand, and then nothing ran them again.
#
# The probe is the thing that tells us the estate is healthy. Its own tests being unrun is the
# same class of fault the probe exists to catch: a check that reports nothing reads exactly like
# a check that reports success.
echo
echo "── bash test files under scripts/ ──"
shopt -s nullglob
BASH_TESTS=("$DIR"/../scripts/test_*.sh)
if [ "${#BASH_TESTS[@]}" -eq 0 ]; then
  echo "  ❌ no scripts/test_*.sh found — this lane was added because those files exist."
  echo "     If they were deliberately removed, remove this lane too; do not leave it green and empty."
  rc=1
fi
# 240s. test_signal_engine_watchdog.sh measured 98s on an idle box on 2026-08-19 — it starts
# real fixture processes and waits real seconds, so it is slow by construction, not stuck. An
# earlier 90s bound killed it mid-run and reported a hang that was not there. 240s leaves head
# room for a loaded box while still bounding a genuinely wedged file, because the failure this
# lane must never have is a test that holds the gate open forever.
for f in "${BASH_TESTS[@]}"; do
  out=$(timeout 240 bash "$f" 2>&1)
  s=$?
  line=$(printf '%s\n' "$out" | grep -aE '[0-9]+ passed, [0-9]+ failed' | tail -1)
  if [ "$s" -eq 124 ]; then
    printf '  ❌ %-40s no verdict in 240s — killed (see the note above this loop)\n' "$(basename "$f")"
    printf '%s\n' "$out" | tail -6 | sed 's/^/       /'
    rc=1
  elif [ "$s" -eq 0 ]; then
    printf '  ✅ %-40s %s\n' "$(basename "$f")" "${line:-exit 0}"
  else
    printf '  ❌ %-40s exit=%s %s\n' "$(basename "$f")" "$s" "${line:-no results line}"
    printf '%s\n' "$out" | tail -12 | sed 's/^/       /'
    rc=1
  fi
done

echo
if [ "$rc" -eq 0 ]; then echo "GATE: PASS"; else echo "GATE: FAIL"; fi
exit "$rc"
