#!/bin/bash
# End-to-end proof for the transient-network classification added to auto-push.sh
# (2026-08-16). Runs the REAL script inside a sandbox $HOME with a real git repo and
# real git failures — no stubbed `git`, no faked output.
#
#   A. DNS failure (remote host in the .invalid TLD, RFC 2606) -> exit 0, exit 0, exit 1
#   B. non-fast-forward rejection                              -> exit 1 on the FIRST try
#   C. successful push                                         -> exit 0 and streak reset
#
# Read-only with respect to the live estate: everything happens under $SB.

set -uo pipefail
SRC="$HOME/.hermes/scripts"
SB="${TMPDIR:-/tmp}/auto-push-net-test.$$"
export GIT_TERMINAL_PROMPT=0 AUTO_PUSH_NET_TIMEOUT=20
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
fails=0
ok()   { printf 'PASS  %s\n' "$*"; }
bad()  { printf 'FAIL  %s\n' "$*"; fails=$((fails + 1)); }
want() { # want <label> <expected> <actual>
  if [ "$2" = "$3" ]; then ok "$1 (got $3)"; else bad "$1 (expected $2, got $3)"; fi
}

# ---------- unit: the classifier itself ----------
. "$SRC/lib/net_transient.sh"
echo "=== A0. is_transient_net() classification ==="
for s in \
  "fatal: unable to access 'https://github.com/x.git/': Could not resolve host: github.com" \
  "ssh: Could not resolve hostname github.com: Temporary failure in name resolution" \
  "fatal: unable to access: Failed to connect: Network is unreachable" \
  "fatal: unable to access: Connection timed out after 90001 ms" \
  "timed out after 90s"
do
  if is_transient_net "$s"; then ok "transient: ${s:0:56}"; else bad "should be transient: $s"; fi
done
for s in \
  "! [rejected] main -> main (non-fast-forward)" \
  "remote: Permission to x.git denied to y. fatal: unable to access: 403" \
  "remote: error: pre-receive hook declined" \
  ""
do
  if is_transient_net "$s"; then bad "should NOT be transient: $s"; else ok "hard fail: ${s:0:56}"; fi
done

# ---------- sandbox ----------
mkdir -p "$SB/home/.hermes/scripts/lib" "$SB/home/.hermes/state"
cp "$SRC/auto-push.sh" "$SB/home/.hermes/scripts/"
cp "$SRC/lib/net_transient.sh" "$SB/home/.hermes/scripts/lib/"
REPO="$SB/home/.hermes"
git -C "$REPO" init -q -b main
git -C "$REPO" config user.email t@t; git -C "$REPO" config user.name t
echo seed >"$REPO/seed.txt"
git -C "$REPO" add -A >/dev/null; git -C "$REPO" commit -qm seed
SKIPS="$REPO/state/auto-push-net-skips"

run() { # run -> prints "rc=<n>"; makes a fresh change first so there is something to sync
  date +%s%N >"$REPO/churn.txt"
  ( HOME="$SB/home" bash "$SB/home/.hermes/scripts/auto-push.sh" ) >"$SB/out" 2>"$SB/err"
  printf '%s' "$?"
}
streak() { cat "$SKIPS" 2>/dev/null || echo "<absent>"; }

# ---------- A. transient DNS failure, three consecutive cycles ----------
echo; echo "=== A. real DNS failure (remote = https://gh-does-not-exist.invalid) ==="
git -C "$REPO" remote add origin "https://gh-does-not-exist.invalid/x.git"
rm -f "$SKIPS"
for n in 1 2 3; do
  rc=$(run)
  echo "--- cycle $n: rc=$rc streak=$(streak)"
  echo "    stderr: $(tr '\n' ' ' <"$SB/err" | cut -c1-160)"
  case $n in
    1|2) want "cycle $n suppressed (exit 0)" 0 "$rc"; want "cycle $n streak" "$n" "$(streak)" ;;
    3)   want "cycle 3 escalates (exit 1)"  1 "$rc"; want "cycle 3 streak" 3 "$(streak)" ;;
  esac
done
echo "--- log tail:"; tail -4 "$REPO/logs/auto-push.log" | sed 's/^/    /'

# ---------- B. non-transient rejection must fail on the FIRST try ----------
echo; echo "=== B. non-fast-forward rejection (real local bare remote, diverged) ==="
git init -q --bare -b main "$SB/bare.git"
git -C "$REPO" remote set-url origin "$SB/bare.git"
git -C "$REPO" push -q origin main
git clone -q "$SB/bare.git" "$SB/other"
git -C "$SB/other" config user.email t@t; git -C "$SB/other" config user.name t
echo diverge >"$SB/other/diverge.txt"
git -C "$SB/other" add -A >/dev/null; git -C "$SB/other" commit -qm diverge; git -C "$SB/other" push -q origin main
rm -f "$SKIPS"                     # streak 0: a fresh, non-transient failure
rc=$(run)
echo "--- rc=$rc streak=$(streak)"
echo "    stderr: $(tr '\n' ' ' <"$SB/err" | cut -c1-200)"
want "non-fast-forward exits 1 immediately" 1 "$rc"
want "non-fast-forward does NOT touch the net-skip counter" "<absent>" "$(streak)"

# ---------- C. a good push resets the streak ----------
echo; echo "=== C. successful push resets the counter ==="
git -C "$REPO" fetch -q origin && git -C "$REPO" merge -q --no-edit origin/main
printf '2\n' >"$SKIPS"             # pretend two offline hours just happened
rc=$(run)
echo "--- rc=$rc streak=$(streak)"
echo "    stdout: $(cat "$SB/out")"
want "successful push exits 0" 0 "$rc"
want "streak reset to 0"       0 "$(streak)"

# ---------- D. corrupt counter must not abort the run ----------
echo; echo "=== D. corrupt counter file is survivable ==="
git -C "$REPO" remote set-url origin "https://gh-does-not-exist.invalid/x.git"
printf 'garbage\n' >"$SKIPS"
rc=$(run)
echo "--- rc=$rc streak=$(streak)"
want "corrupt counter -> treated as 0, suppressed" 0 "$rc"
want "corrupt counter -> rewritten as 1"           1 "$(streak)"

rm -rf "$SB"
echo; if [ "$fails" -eq 0 ]; then echo "ALL CHECKS PASSED"; else echo "$fails CHECK(S) FAILED"; fi
exit "$fails"
