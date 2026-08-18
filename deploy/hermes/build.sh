#!/usr/bin/env bash
# Build the Hermes image. One command, because the build needs two source trees and getting
# that wrong fails late and confusingly - as a container that starts and then has two of its
# six programs sit in FATAL.
#
#   bash deploy/hermes/build.sh            # -> hermes:local
#   bash deploy/hermes/build.sh registry/hermes:sha
#
# SENTINEL_LOOP points at the second tree. It defaults to the laptop checkout; on a builder
# that has it somewhere else, set the variable rather than editing this file.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
TAG="${1:-hermes:local}"
SENTINEL_LOOP="${SENTINEL_LOOP:-$HOME/Documents/code/sentinel-loop}"

[ -d "$SENTINEL_LOOP/sentinel" ] || {
  echo "no sentinel-loop checkout at $SENTINEL_LOOP" >&2
  echo "clone https://github.com/chidionyema/sentinel-loop.git or set SENTINEL_LOOP" >&2
  exit 1
}

# BuildKit, for the named context. Docker 24 defaults to it; this is explicit so an older
# daemon fails with a clear message instead of choking on COPY --from=sentinel-loop.
export DOCKER_BUILDKIT=1

cd "$ROOT"
docker build \
  -f deploy/hermes/Dockerfile \
  --build-context "sentinel-loop=$SENTINEL_LOOP" \
  -t "$TAG" \
  .
echo "built $TAG"
