#!/usr/bin/env python3
"""launchd_receipt.py — sign a capability receipt around any launchd job.

WHY THIS EXISTS. cron/scheduler.py::_write_receipt gives every HERMES CRON job a durable
"did it work" record, and reliability_report.py turns those records into verdicts that
reach the founder (the reliability-watchdog job is registered deliver="origin"). launchd
jobs were never in that layer, and the cost is measured rather than hypothetical:

    launchctl print gui/501/com.prospector.backup
        runs = 9
        last exit code = 1

Nine consecutive failed runs, 237 dossiers never uploaded, and nothing raised — because a
job that signs no receipt is invisible to the audit that decides what is broken. Seven
launchd jobs sit in that blind spot.

This wrapper runs the real command, passes its output through unchanged (so the plist's
StandardOutPath/StandardErrorPath still capture everything), and appends ONE receipt in
exactly the shape capability_audit.py:143-190 matches on — keyed by the `script` basename,
carrying exit_code and artifact_count. Register a matching receipt-kind capability in
~/.hermes/capabilities.json and the job joins the same alarm chain as every cron job.

The receipt write is best-effort and always last: observing a job must never be able to
fail it. The wrapper's exit code is the child's, unchanged, so launchd's own accounting
(and any KeepAlive policy) behaves exactly as before.

Usage from a plist:
    <array>
      <string>/usr/bin/python3</string>
      <string>/Users/you/.hermes/scripts/launchd_receipt.py</string>
      <string>--label</string><string>com.prospector.backup</string>
      <string>--artifact-dir</string><string>/path/to/watch</string>
      <string>--</string>
      <string>/real/program</string><string>--flag</string>
    </array>
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes"))
RECEIPTS = HERMES_HOME / "state" / "capability_receipts.jsonl"

# Directory names that never count as produced work. A job that only wrote a log line has
# not done its job — this is the same "exit-0-did-nothing" class the cron receipts exist to
# catch, so the exclusion list has to match in spirit.
_IGNORED_DIRS = {"logs", ".git", "__pycache__", "node_modules", ".venv", "state"}
_IGNORED_SUFFIXES = {".log", ".pyc", ".lock", ".tmp"}


def _scan_produced(root: Path, started: float, limit: int = 5000) -> list[str]:
    """Files under `root` modified after `started`, as repo-relative names.

    Bounded by `limit` so pointing this at a huge tree degrades to a slow-but-finite walk
    rather than hanging the job it is supposed to be observing.
    """
    out: list[str] = []
    seen = 0
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _IGNORED_DIRS and not d.startswith(".")]
            for name in filenames:
                seen += 1
                if seen > limit:
                    return out
                if any(name.endswith(s) for s in _IGNORED_SUFFIXES):
                    continue
                full = Path(dirpath) / name
                try:
                    if full.stat().st_mtime >= started:
                        out.append(str(full.relative_to(root)))
                except OSError:
                    continue
    except OSError:
        return out
    return out


# Interpreters whose FIRST argument is the thing actually being run. Without this, an
# invocation like [".venv/bin/python", "backup_store.py"] would be keyed as "python" and
# every python job on the estate would collide on one receipt key — while a plain program
# with flags, ["mytool", "--flag"], must NOT be keyed as "--flag".
_INTERPRETERS = {"python", "python3", "bash", "sh", "zsh", "node", "ruby", "perl"}


def _default_script_key(cmd: list[str]) -> str:
    """The receipt key: the script being run, not the interpreter running it.

    `-c` and `-m` are why this is not a one-line "first non-flag argument". Their operand
    is CODE, not a path: a naive scan of `bash -c "echo hi; touch out/produced.json"`
    derives the key "produced.json" — a receipt keyed on an incidental word inside a shell
    string, which would silently never match any registered capability. Caught by test (a)
    on 2026-08-07.
    """
    head = os.path.basename(cmd[0])
    stem = head[:-4] if head.endswith(".exe") else head
    if not (stem in _INTERPRETERS or stem.startswith("python")):
        return head

    rest = cmd[1:]
    i = 0
    while i < len(rest):
        arg = rest[i]
        if arg == "-c":
            # Inline code — there is no script file to name. Fall back to the interpreter;
            # a caller that wants a meaningful key must pass --script.
            return head
        if arg == "-m":
            return rest[i + 1] if i + 1 < len(rest) else head
        if arg.startswith("-"):
            i += 1
            continue
        return os.path.basename(arg)
    return head


def _write_receipt(script: str, label: str, started: float, exit_code: int,
                   stdout: str, stderr: str, artifacts: list[str]) -> None:
    """Append one receipt. Never raises — observation must not break the observed."""
    try:
        rec = {
            "script": script,
            "label": label,
            "source": "launchd",
            "started_at": started,
            "ended_at": time.time(),
            "duration_s": round(time.time() - started, 2),
            "exit_code": exit_code,
            "stdout_bytes": len(stdout or ""),
            "artifact_count": len(artifacts),
            "artifacts": artifacts[:40],
            "log_count": 0,
            "attribution": "wrapper",
        }
        if exit_code != 0:
            # Matches the cron receipt's `error_tail`: a DARK verdict with no cause is one
            # nobody can act on. stderr first — a failing job usually says why there.
            tail = ((stderr or "").strip() or (stdout or "").strip())
            if tail:
                rec["error_tail"] = tail[-2000:]
        RECEIPTS.parent.mkdir(parents=True, exist_ok=True)
        with open(RECEIPTS, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
    except Exception:  # noqa: BLE001
        print(f"launchd_receipt: receipt write failed for {script}", file=sys.stderr)

    # Bound the ledger. This is the only automatic caller of maybe_rotate, which is why
    # it sits on the wrapper's path rather than the audit's: the wrapped jobs include
    # 5- and 15-minute ones, so the (single-stat) check runs hundreds of times a day and
    # the ledger cannot outrun it. Rotation itself only fires above 8MB. See
    # receipt_rotate.py for why truncation without the __origin__ marker is a bug.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from receipt_rotate import maybe_rotate

        maybe_rotate(RECEIPTS)
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--label", required=True, help="launchd label, recorded on the receipt")
    ap.add_argument("--script", default=None,
                    help="receipt key; defaults to the basename of the program. This is "
                         "what capabilities.json must name in observable.script.")
    ap.add_argument("--artifact-dir", action="append", default=[],
                    help="scan this directory for files written during the run (repeatable)")
    ap.add_argument("command", nargs=argparse.REMAINDER,
                    help="-- followed by the real program and its arguments")
    args = ap.parse_args()

    cmd = args.command
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("launchd_receipt: no command given after --", file=sys.stderr)
        return 2

    script = args.script or _default_script_key(cmd)

    started = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        stdout, stderr, code = result.stdout or "", result.stderr or "", result.returncode
    except Exception as exc:  # the program could not be spawned at all
        stdout, stderr, code = "", f"{type(exc).__name__}: {exc}", 127

    # Pass the child's output through untouched FIRST, so the plist's log files see exactly
    # what they saw before this wrapper existed.
    if stdout:
        sys.stdout.write(stdout)
        sys.stdout.flush()
    if stderr:
        sys.stderr.write(stderr)
        sys.stderr.flush()

    artifacts: list[str] = []
    for d in args.artifact_dir:
        p = Path(os.path.expanduser(d))
        if p.is_dir():
            artifacts.extend(_scan_produced(p, started))

    _write_receipt(script, args.label, started, code, stdout, stderr, artifacts)
    return code


if __name__ == "__main__":
    sys.exit(main())
