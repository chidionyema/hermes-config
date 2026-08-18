#!/usr/bin/env bash
# Build the Hermes image locally. Only needed to debug the image; deploy.sh does NOT use this
# and needs no Docker daemon at all.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
TAG="${1:-hermes:local}"
SENTINEL_LOOP="${SENTINEL_LOOP:-$HOME/Documents/code/sentinel-loop}"
[ -d "$SENTINEL_LOOP/sentinel" ] || { echo "no sentinel-loop checkout at $SENTINEL_LOOP" >&2; exit 1; }
trap 'rm -rf "$ROOT/vendor"' EXIT INT TERM
rm -rf "$ROOT/vendor"; mkdir -p "$ROOT/vendor"
cp -Rc "$SENTINEL_LOOP" "$ROOT/vendor/sentinel-loop" 2>/dev/null \
  || cp -R "$SENTINEL_LOOP" "$ROOT/vendor/sentinel-loop"
export DOCKER_BUILDKIT=1
cd "$ROOT"
docker build -f deploy/hermes/Dockerfile -t "$TAG" .
echo "built $TAG"
