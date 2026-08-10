#!/bin/bash
## runaway-reaper.sh — reap long-lived CPU hogs that starve the host.
##
## WHY: bounded phases in idle-learning-run.sh blow PHASE_TIMEOUT=30s (rc=124)
## whenever the 12-CPU box is saturated by orphaned recursive greps and stale
## `pi` (MiniMax bridge) executors. Measured 2026-08-10: 1-min loadavg 115-283
## with four such processes resident; the same two phases exit 0 in 8s/15s when
## run standalone. The phases are not the defect — the host is.
##
## CONTRACT:
##   - Match on ARGV + AGE only. Never whitelist a PID: PIDs are recycled and a
##     restart re-creates the same runaway under a new number.
##   - SIGTERM, grace, then SIGKILL. Never SIGKILL first (no chance to flush).
##   - Every kill is appended to logs/maintenance/runaway-reaper.jsonl.
##   - --dry-run prints the match set and kills nothing (used to prove the
##     matcher without touching live processes).
##
## Reap rules (age thresholds in seconds):
##   grep invoked with a recursive flag (-r/-R/--recursive) .... > 300
##   pi (MiniMax bridge executor) ............................. > 3600
##   chrome-headless-shell .................................... > 1800

set -uo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
LOG_DIR="$HERMES_HOME/logs/maintenance"
REAP_LOG="$LOG_DIR/runaway-reaper.jsonl"
GRACE="${REAPER_GRACE:-5}"

GREP_MAX_AGE="${REAPER_GREP_MAX_AGE:-300}"
PI_MAX_AGE="${REAPER_PI_MAX_AGE:-3600}"
CHROME_MAX_AGE="${REAPER_CHROME_MAX_AGE:-1800}"

DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

mkdir -p "$LOG_DIR"

SELF_PID=$$

# Emit "pid<TAB>age_seconds<TAB>rule<TAB>argv" for every process that matches a
# reap rule. etime is parsed in awk because BSD/macOS ps has no `etimes` keyword
# (verified 2026-08-10: `ps: etimes: keyword not found`).
candidates() {
  ps -Ao pid=,etime=,args= | awk -v self="$SELF_PID" \
      -v gmax="$GREP_MAX_AGE" -v pimax="$PI_MAX_AGE" -v cmax="$CHROME_MAX_AGE" '
    function etime_secs(e,   d, hms, n, p, s) {
      d = 0
      if (e ~ /-/) { n = index(e, "-"); d = substr(e, 1, n - 1) + 0; e = substr(e, n + 1) }
      n = split(e, p, ":")
      if (n == 3)      s = p[1] * 3600 + p[2] * 60 + p[3]
      else if (n == 2) s = p[1] * 60 + p[2]
      else             s = p[1] + 0
      return d * 86400 + s
    }
    {
      pid = $1 + 0
      age = etime_secs($2)
      argv = ""
      for (i = 3; i <= NF; i++) argv = argv (i > 3 ? " " : "") $i
      if (pid == self || pid <= 1) next
      # the argv of this reaper (and any editor viewing it) must never match
      if (argv ~ /runaway-reaper/) next

      cmd = $3
      n = split(cmd, seg, "/"); base = seg[n]

      rule = ""
      # (a) recursive grep: basename is a grep variant AND some later arg carries
      #     a recursive flag. `-v`/`--include` alone must NOT match.
      if (base ~ /^(grep|egrep|fgrep|ggrep|rgrep)$/) {
        rec = 0
        for (i = 4; i <= NF; i++) {
          if ($i == "--recursive" || $i == "--dereference-recursive") rec = 1
          else if ($i ~ /^-[a-zA-Z]*[rR]/ && $i !~ /^--/) rec = 1
        }
        if (rec && age > gmax) rule = "recursive-grep"
      }
      # (b) stale MiniMax bridge executor
      else if (base == "pi" && age > pimax) rule = "stale-pi"
      # (c) leaked headless browser
      else if (base ~ /^chrome-headless-shell$/ && age > cmax) rule = "chrome-headless-shell"

      if (rule != "") printf "%d\t%d\t%s\t%s\n", pid, age, rule, argv
    }'
}

log_kill() {
  local pid="$1" age="$2" rule="$3" argv="$4" signal="$5"
  python3 - "$pid" "$age" "$rule" "$argv" "$signal" "$REAP_LOG" <<'PY'
import json, sys, datetime
pid, age, rule, argv, signal, path = sys.argv[1:7]
rec = {
    "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "pid": int(pid),
    "age_s": int(age),
    "rule": rule,
    "signal": signal,
    "argv": argv[:500],
}
with open(path, "a") as fh:
    fh.write(json.dumps(rec) + "\n")
PY
}

MATCHED=0
TERMED=()
while IFS=$'\t' read -r pid age rule argv; do
  [ -z "${pid:-}" ] && continue
  MATCHED=$((MATCHED + 1))
  if [ "$DRY_RUN" -eq 1 ]; then
    printf 'DRY-RUN would reap pid=%s age=%ss rule=%s argv=%.120s\n' "$pid" "$age" "$rule" "$argv"
    continue
  fi
  echo "reaping pid=$pid age=${age}s rule=$rule"
  kill -TERM "$pid" 2>/dev/null && log_kill "$pid" "$age" "$rule" "$argv" "SIGTERM"
  TERMED+=("$pid|$age|$rule|$argv")
done < <(candidates)

if [ "$DRY_RUN" -eq 0 ] && [ "${#TERMED[@]}" -gt 0 ]; then
  sleep "$GRACE"
  for entry in "${TERMED[@]}"; do
    IFS='|' read -r pid age rule argv <<< "$entry"
    if kill -0 "$pid" 2>/dev/null; then
      kill -KILL "$pid" 2>/dev/null && log_kill "$pid" "$age" "$rule" "$argv" "SIGKILL"
    fi
  done
fi

echo "runaway-reaper: matched=$MATCHED dry_run=$DRY_RUN load=$(sysctl -n vm.loadavg | awk '{print $2+0}')"
exit 0
