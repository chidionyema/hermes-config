#!/usr/bin/env bash
# Regression test for auto-push.sh's credential backstop.
#
# WHY THIS EXISTS: .gitignore is name-based and this repo missed the same class of
# file three times — `*.env` never matched `.env.bak-20260805-222102` (committed in
# 6ed5d40 and PUSHED with 26 live values), and neither `*.bak-*` nor `*.bak.*`
# matched `config.yaml.corrupt.20260617-135424.bak` (still tracked on 2026-08-06,
# holding the DeepSeek key live in .env that day). auto-push.sh does a bare
# `git commit` of everything staged, so the content guard is the only control that
# does not depend on someone predicting the next filename.
#
# The regex is EXTRACTED FROM auto-push.sh rather than copied, so this test cannot
# pass against a pattern the real script no longer uses.
#
# Usage: bash scripts/test_auto_push_secret_guard.sh    (exit 0 = guard bites)
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/auto-push.sh"

SECRET_RE=$(sed -n "s/^SECRET_RE='\(.*\)'$/\1/p" "$SRC")
if [ -z "$SECRET_RE" ]; then
  echo "FAIL: could not extract SECRET_RE from $SRC — the guard was renamed or removed" >&2
  exit 1
fi
echo "extracted SECRET_RE from auto-push.sh (${#SECRET_RE} chars)"

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
cd "$T"; git init -q .; git config user.email t@t; git config user.name t
# `git restore --staged` resolves against HEAD; with no commits it cannot unstage
# anything and every case reads as leaked. Seed a HEAD so the test measures the guard.
echo seed > .seed; git add .seed; git commit -qm seed

# Positive controls — synthetic, never real values.
printf 'ANTHROPIC_API_KEY=sk-ant-api03-%s\n' "$(printf 'A%.0s' {1..40})"  > p1_env.bak
printf 'deepseek: sk-%s\n' "$(printf 'a%.0s' {1..32})"                    > p2_config.yaml
printf 'GEMINI=AIza%s\n' "$(printf 'B%.0s' {1..35})"                      > p3.txt
printf 'bot: 8656132729:AA%s\n' "$(printf 'C%.0s' {1..33})"               > p4.json
printf 'TELEGRAM_WEBHOOK_SECRET = "%s"\n' "$(printf 'd%.0s' {1..30})"     > p5.ini
# Negative controls. n4 is binary: `grep -I` must skip it, because bin/tirith is a
# Mach-O whose compiled-in secret DETECTION patterns match these same regexes.
printf 'ANTHROPIC_API_KEY=your-key-here\n'                                > n1.env.example
printf '# set sk-ant-... in your shell\n'                                 > n2_docs.md
printf 'API_KEY=\n'                                                       > n3.conf
head -c 400 /dev/urandom                                                  > n4_binary.bin

git add -A
while IFS= read -r f; do
  [ -f "$f" ] || continue
  grep -IqE "$SECRET_RE" -- "$f" 2>/dev/null && git restore --staged -- "$f" 2>/dev/null
done < <(git diff --cached --name-only --diff-filter=ACM)

fail=0
staged() { git diff --cached --name-only | grep -qx "$1"; }
for f in p1_env.bak p2_config.yaml p3.txt p4.json p5.ini; do
  if staged "$f"; then echo "  FAIL leaked: $f"; fail=1; else echo "  ok  refused: $f"; fi
done
for f in n1.env.example n2_docs.md n3.conf n4_binary.bin; do
  if staged "$f"; then echo "  ok  kept:    $f"; else echo "  FAIL false-positive: $f"; fail=1; fi
done
echo
[ $fail -eq 0 ] && echo "PASS: 5/5 credential shapes refused, 0/4 false positives" \
                || echo "FAIL: guard does not bite"
exit $fail
