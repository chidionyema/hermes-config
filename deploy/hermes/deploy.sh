#!/usr/bin/env bash
# Ship Hermes to Fly WITHOUT a local Docker daemon.
#
# WHY NO LOCAL BUILD. Docker Desktop held 4.8GB and 29% CPU on a box whose four CI runners
# already claim every thread, so the founder stopped it - and the build then died mid-`COPY`
# with `failed to receive status: rpc error ... EOF`, which reads like a network fault rather
# than a daemon that is not there. Fly's remote builder does the work instead: this script
# sends a build context and nothing else.
#
# WHY THE STAGING STEP. The image needs a second repo, sentinel-loop, at an absolute path.
# `docker build --build-context` can supply that; `flyctl deploy` has no such flag. So the
# repo is cloned into the build context as vendor/sentinel-loop and removed on every exit
# path, including a failure.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
APP="${PROSPECTOR_HERMES_APP:-prospector-hermes}"
SENTINEL_LOOP="${SENTINEL_LOOP:-$HOME/Documents/code/sentinel-loop}"

[ -d "$SENTINEL_LOOP/sentinel" ] || { echo "no sentinel-loop checkout at $SENTINEL_LOOP" >&2; exit 1; }

# ── THE GATE ───────────────────────────────────────────────────────────────────────────────
#
# This script deploys the WORKING TREE, not a commit. Until 2026-08-19 that meant anything
# sitting in ~/.hermes reached production, reviewed or not, committed or not, and the deploy
# reported success either way. Prospector reaches production through a PR and a green CI run;
# Hermes reached it through whatever a session had left on the laptop.
#
# So: refuse a tree that is not exactly what is on origin/main, and run the gate first.
# PROSPECTOR_HERMES_DEPLOY_FORCE=1 is the escape hatch for an incident, and it says out loud
# what it is doing rather than passing quietly.
if [ "${PROSPECTOR_HERMES_DEPLOY_FORCE:-0}" = "1" ]; then
  echo "deploy: FORCED — the tree is being shipped without the gate. Say why in the incident log." >&2
else
  # Paths the running agent rewrites are declared in runtime-written.txt, with a
  # reason each. Anything that looks like source is refused there rather than
  # honoured, so this filter can never wave a code change through.
  runtime_list="$HERE/runtime-written.txt"
  ignore_re='^\.\. vendor/'
  if [ -f "$runtime_list" ]; then
    while IFS= read -r entry; do
      case "$entry" in ''|'#'*) continue ;; esac
      case "$entry" in
        *.py|*.sh|*.ts|*.js|*.tsx|*.jsx|scripts/*|hermes-agent/*|tests/*|deploy/*)
          echo "deploy: REFUSED — runtime-written.txt lists '$entry', which is code." >&2
          echo "        That list is for state the agent writes, never for source." >&2
          exit 1 ;;
      esac
      ignore_re="$ignore_re|^.. $(printf '%s' "$entry" | sed 's/[.[\*^$]/\\&/g')"
    done < "$runtime_list"
  fi
  dirty="$(git -C "$ROOT" status --porcelain --untracked-files=no | grep -Ev "$ignore_re" || true)"
  if [ -n "$dirty" ]; then
    echo "deploy: REFUSED — uncommitted changes. Commit and push them, or set" >&2
    echo "        PROSPECTOR_HERMES_DEPLOY_FORCE=1 for an incident." >&2
    printf '%s\n' "$dirty" >&2
    exit 1
  fi
  git -C "$ROOT" fetch --quiet origin main || true
  local_head="$(git -C "$ROOT" rev-parse HEAD)"
  remote_head="$(git -C "$ROOT" rev-parse origin/main)"
  if [ "$local_head" != "$remote_head" ]; then
    echo "deploy: REFUSED — HEAD is $local_head but origin/main is $remote_head." >&2
    echo "        A deploy must be reproducible from the remote. Push, or pull." >&2
    exit 1
  fi
  echo "deploy: tree is clean and matches origin/main ($local_head)"
  echo "deploy: running the gate — tests/run.sh"
  if ! PYTHON="${PYTHON:-$ROOT/hermes-agent/venv/bin/python}" bash "$ROOT/tests/run.sh" >"$ROOT/.deploy-gate.log" 2>&1; then
    echo "deploy: REFUSED — the gate failed. Last 20 lines:" >&2
    tail -20 "$ROOT/.deploy-gate.log" >&2
    exit 1
  fi
  echo "deploy: gate passed"
fi

# Trap set BEFORE the copy, so an interrupt never leaves a second repo inside this one.
trap 'rm -rf "$ROOT/vendor"' EXIT INT TERM
rm -rf "$ROOT/vendor"
mkdir -p "$ROOT/vendor"
# -c is an APFS copy-on-write clone: instant, and no second 26MB on disk. Falls back to a
# real copy on any filesystem that cannot clone.
cp -Rc "$SENTINEL_LOOP" "$ROOT/vendor/sentinel-loop" 2>/dev/null \
  || cp -R "$SENTINEL_LOOP" "$ROOT/vendor/sentinel-loop"

cd "$ROOT"
flyctl deploy . \
  --config deploy/hermes/fly.toml \
  --dockerfile deploy/hermes/Dockerfile \
  --app "$APP" \
  --remote-only \
  --ha=false \
  --yes
echo "deployed $APP"
