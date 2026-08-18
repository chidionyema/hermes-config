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
