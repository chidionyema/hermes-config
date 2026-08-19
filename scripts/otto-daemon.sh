#!/bin/bash
# Otto daemon — kept alive by launchd (ai.hermes.otto-server)
# Loads the hermes AI agent and exposes it via HTTP on 127.0.0.1:8802
export HOME=/Users/chidionyema

# Load secrets from .env line by line (safe for values with spaces)
ENV_FILE="$HOME/.hermes/.env"
if [ -f "$ENV_FILE" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [ -z "$line" ] && continue
    case "$line" in
      \#*) continue ;;
    esac
    case "$line" in
      *=*)
        key="${line%%=*}"
        val="${line#*=}"
        val="${val#\"}"; val="${val%\"}"
        val="${val#\'}"; val="${val%\'}"
        [ -n "$key" ] && export "$key=$val"
        ;;
    esac
  done < "$ENV_FILE"
fi

# The otto server needs the hermes-agent package on PYTHONPATH
export PYTHONPATH="$HOME/.hermes/hermes-agent:$PYTHONPATH"
cd "$HOME/.hermes/hermes-agent"
# Use the hermes-agent VENV interpreter, not a bare /usr/local/bin/python3. The bare one has no
# `anthropic` package, so otto crash-looped under KeepAlive with
# `ImportError: The 'anthropic' package is required for the Anthropic provider` — a dependency
# error that is really a wrong-interpreter error. The venv is where every other hermes service
# resolves its deps (ai.hermes.gateway runs hermes-agent/venv/bin/python) and it has
# anthropic 0.87.0. Fail LOUDLY if it is missing rather than silently falling back to a python
# that cannot serve: a silent fallback is what made this look like a packaging problem.
# ROOT CAUSE 2: `OSError: [Errno 48] Address already in use` on bind. This is NOT a TIME_WAIT
# race — http.server.HTTPServer sets allow_reuse_address=1, so SO_REUSEADDR is already on and
# EADDRINUSE means a LIVE second listener holds 8802. Combined with KeepAlive=true that wedges
# otto permanently: every restart dies identically, forever, and the log blames the port.
# So refuse to start into a held port, and distinguish the two cases rather than killing blind.
PORT=8802
holders="$(/usr/sbin/lsof -nP -tiTCP:$PORT -sTCP:LISTEN 2>/dev/null)"
if [ -n "$holders" ]; then
  for pid in $holders; do
    cmd="$(ps -o command= -p "$pid" 2>/dev/null)"
    case "$cmd" in
      *otto_server.py*)
        echo "[otto] port $PORT held by a stale otto_server.py (pid $pid) — terminating it" >&2
        kill -TERM "$pid" 2>/dev/null
        ;;
      *)
        # Never kill a process we cannot identify as ours. A daemon that reclaims a port by
        # force is a worse failure than one that will not start.
        echo "[otto] FATAL: port $PORT held by a NON-otto process: pid $pid ($cmd)" >&2
        echo "[otto] refusing to kill a stranger. Resolve the conflict, then restart otto." >&2
        exit 78
        ;;
    esac
  done
  for _ in $(seq 1 40); do
    /usr/sbin/lsof -nP -tiTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1 || break
    /bin/sleep 0.25
  done
  if /usr/sbin/lsof -nP -tiTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
    echo "[otto] FATAL: port $PORT still held 10s after TERM; not starting, to avoid an" >&2
    echo "[otto] EADDRINUSE crash loop that would restart forever and blame the port." >&2
    exit 75   # EX_TEMPFAIL — the condition may clear on its own
  fi
fi

VENV_PY="$HOME/.hermes/hermes-agent/venv/bin/python"
if [ ! -x "$VENV_PY" ]; then
  echo "[otto] FATAL: $VENV_PY missing. Otto's deps (anthropic) live in the hermes-agent venv;" >&2
  echo "[otto] refusing to start on a bare interpreter that will ImportError under KeepAlive." >&2
  exit 78   # EX_CONFIG — a config error, not a transient one
fi
exec "$VENV_PY" \
  "$HOME/Documents/code/sentinel-loop/scripts/otto_server.py" 8802
