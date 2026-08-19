#!/usr/bin/env bash
# Give the Hermes gate the one credential it needs, and nothing more.
#
# THE PROBLEM. hermes-agent is a private submodule in a different repository from the one CI
# checks out. GITHUB_TOKEN is scoped to a single repository, so no setting on actions/checkout
# can reach it. Something must be stored.
#
# WHY A DEPLOY KEY AND NOT A PAT. This runs on a self-hosted runner that executes branch code.
# A personal access token there is the founder's whole account sitting in a container that runs
# whatever a pull request contains. A deploy key reads exactly one repository, writes nothing,
# and is revoked by deleting one row. Narrowest thing that works, so it is the thing that ships.
#
# WHAT IT TOUCHES: one read-only key on chidionyema/hermes-agent, and one Actions secret on
# chidionyema/hermes-config. The private half is written to a 600 file in a temporary directory,
# piped to `gh` on stdin, and deleted on every exit path including a failure. It is never an
# argument, so it never reaches `ps` output or a shell history file, and it is never printed.
set -euo pipefail

AGENT_REPO="${AGENT_REPO:-chidionyema/hermes-agent}"
CI_REPO="${CI_REPO:-chidionyema/hermes-config}"
SECRET_NAME="HERMES_AGENT_DEPLOY_KEY"

command -v gh >/dev/null || { echo "gh is not installed" >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "gh is not logged in - run: gh auth login" >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT INT TERM
KEY="$TMP/hermes_agent"

ssh-keygen -t ed25519 -N '' -C "hermes-config CI (read-only)" -f "$KEY" -q
echo "minted $(ssh-keygen -lf "$KEY.pub" | awk '{print $1, $2}')"

# read_only=true is the whole point of this script. -F, not -f, so it is sent as a JSON boolean.
gh api -X POST "repos/$AGENT_REPO/keys" \
  -f title="hermes-config CI (read-only)" \
  -f key="$(cat "$KEY.pub")" \
  -F read_only=true \
  --jq '"deploy key \(.id) added to '"$AGENT_REPO"', read_only=\(.read_only)"'

gh secret set "$SECRET_NAME" --repo "$CI_REPO" < "$KEY"
echo "secret $SECRET_NAME set on $CI_REPO"

cat <<'MSG'

Done. Prove it end to end:

  gh workflow run gate.yml --repo chidionyema/hermes-config
  gh run list --repo chidionyema/hermes-config --workflow gate.yml --limit 1

To revoke: delete the key row on chidionyema/hermes-agent (Settings -> Deploy keys) and
  gh secret delete HERMES_AGENT_DEPLOY_KEY --repo chidionyema/hermes-config
MSG
