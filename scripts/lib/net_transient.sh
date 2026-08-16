#!/bin/bash
# Shared classifier for transient network failures.
#
# Why this exists (2026-08-16): auto-push.sh treated every non-zero `git push` rc the same
# way — log "retry next cycle", exit 1. The scheduler records that as last_status=error and
# the health watchdog escalates it to CRON_ERROR. On 2026-08-16 at 09:12 the machine simply
# had no DNS for a minute ("Could not resolve host: github.com", rc=128). The commit had
# already succeeded and the next hourly cycle pushes it. A self-healing job reported a hard
# failure for a transient offline minute.
#
# This library only DEFINES a function. It runs nothing at source time, so sourcing it can
# never abort a `set -e` script.

# is_transient_net "<git output>"
#   returns 0 when the text looks like a transient network/DNS/TLS condition
#   returns 1 otherwise (auth denied, non-fast-forward, pre-receive rejection, ...)
is_transient_net() {
  printf '%s' "${1:-}" | grep -Eqi \
    'could not resolve host|could not resolve proxy|temporary failure in name resolution|network is unreachable|connection timed out|connection refused|operation timed out|ssl_error_syscall|the remote end hung up unexpectedly|timed out after'
}
