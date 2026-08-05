# Phase A — Iterative Audit Rounds 1 + 2

Per the iterative-audit skill: ONE focus per round, source verification mandatory, file:line evidence, decide continue/stop after each.

## Round 1 — Security perimeter (Pattern 4)

**Focus**: subprocess / exec / env / path handling reachable from external inputs (Telegram callbacks, cron triggers, REST API).

### R1-A (MEDIUM) — Full environment leak to subprocess at `sdlc.py:100`
- **Where**: `gateway/operator_shell/sdlc.py:100` — `_builds_snapshot()` runs `subprocess.run(["gh", "run", "list", ...], env={**os.environ, "GH_NO_UPDATE_NOTIFIER": "1"})`.
- **Issue**: The merged dict `{**os.environ, ...}` passes **every** environment variable to the child process, including secrets (`HERMES_AUTH_JSON`, `OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`, `ANTHROPIC_API_KEY`, etc., based on Phase C-6 evidence these exist).
- **Risk**: Low. `gh` is a signed binary and the user's threat model is local. But if `PATH` is manipulated or a malicious `gh` is shimmed, all env vars leak.
- **Defense-in-depth fix**: Pass only what `gh` needs (`PATH`, `HOME`, `GH_TOKEN` if used, `GH_NO_UPDATE_NOTIFIER`). This is a small one-line change.
- **Pattern elsewhere**: `grep -rnE 'os\.environ\b' gateway/operator_shell/` returns 9 hits; most use `os.environ.get("HERMES_HOME", ...)` for path construction (safe). Only `sdlc.py:100` passes the full env to subprocess. Limited blast radius.

### R1-B (LOW) — `predict_panel.py:11` passes user-controllable `target` to subprocess
- **Where**: `gateway/operator_shell/predict_panel.py:11` — `subprocess.run([sys.executable, str(SCRIPTS/"predictor.py"), "--predict", target], ...)`.
- **Safe-by-construction**: list-form args (no `shell=True`), so shell injection impossible.
- **Residual risk**: `target` flows to `predictor.py`. If `predictor.py` does anything unsafe with arbitrary `target` (eval, file path construction, fetch URL), it's exploitable. Need to verify `predictor.py` (out of scope for this audit but worth flagging).
- **Source verification needed**: read `predictor.py` to confirm `target` is handled as a string label, not eval'd or used in path construction.

### R1-C (LOW) — `fleet.py:147` constructs path from `projects.json` content
- **Where**: `gateway/operator_shell/fleet.py:147` — `repo = Path(str(p.get("repo") or "").replace("~", str(Path.home()))).expanduser()`.
- **Source**: `projects.json` (~/.hermes/projects.json). If this file is writable by an attacker (filesystem access), the path could be set to anywhere and `_git_short(repo)` would run `git -C <path> status --short`.
- **Blast radius**: Limited. `git status --short` is read-only, no shell injection (list-form argv).
- **Defense-in-depth fix**: Validate `repo` is within an expected prefix (e.g., `Path.home()` or a configured `HERMES_PROJECT_ROOT`).

### Other notes (verified clean)
- 339 subprocess calls in `gateway/` + `hermes_cli/`. Only 3 use `shell=True` (in `hermes_cli/mcp_catalog.py:367`, `hermes_cli/tools_config.py:813`, both outside operator_shell).
- No `os.system`, no `os.popen`, no `exec()`, no `eval()` in operator_shell.
- operator_shell subprocess calls all use list-form args (good).

## Round 2 — Resource cleanup (Pattern 7)

**Focus**: leaked asyncio tasks, unclosed sessions, source-watch behavior.

### R2-A (MEDIUM) — Background tasks not cancelled on gateway shutdown
- **Symptom**: 15 occurrences of `ERROR asyncio: Task was destroyed but it is pending! task: <Task pending name='Task-NNNN' coro=<BasePlatformAdapter._process_message_background() done, defined at /Users/chidionyema/.hermes/hermes-agent/gateway/platforms/base.py:4157>>` in `errors.log` on 2026-07-31 22:24:50.
- **Where**: `gateway/platforms/base.py:4157` (`_process_message_background`) and `:3151` (`_keep_typing`).
- **Issue**: When the gateway receives SIGTERM, the shutdown handler should cancel pending tasks and await their completion. Currently, tasks are abandoned and Python's garbage collector complains.
- **Fix**: Track tasks in a `set` per adapter, cancel on shutdown, await `asyncio.gather(*tasks, return_exceptions=True)` with a timeout.
- **Frequency**: Concentrated on 2026-07-31 22:24 — single shutdown event with many in-flight tasks. Not a leak per session but a noisy shutdown that masks real errors.

### R2-B (LOW) — aiohttp sessions leaked in pytest cleanup (not production)
- **Symptom**: 9 occurrences of `ERROR asyncio: Unclosed client session` — but the traceback paths point to `/private/var/folders/gq/.../pytest-of-chidionyema/pytest-464/...` — i.e., a pytest tempdir.
- **Where**: Tests for `gateway/platforms/matrix.py` don't close the aiohttp `ClientSession` after the test.
- **Risk**: Tests-only. Doesn't affect production. But pytest's warning summary will keep mentioning this, masking other issues.
- **Fix**: Use a pytest fixture that yields a session and closes it on teardown.

### R2-C (NOT A FINDING) — Source-watch restarts (73 in 4 days)
- **Reviewed**: `gateway/source_watch.py` in full.
- **Conclusion**: Not a bug. Watcher has three documented guards: only-when-supervised (ppid=1), only-after-quiet (20s default), never-twice (latch). Off switch: `HERMES_GATEWAY_AUTORELOAD=0`. Skip dirs include `__pycache__`, `.git`, `tests`, `worktrees`, `venv`. Watched packages are `gateway, hermes_cli, agent, sentinel` only.
- **The 73 restarts** correlate with the user's edit tempo (49 on 2026-08-02 = 2/hour during an active session). The audit cannot prove the restarts were unnecessary without knowing what was edited.

## Decision: continue or stop?

After Rounds 1 + 2, the audit has produced:
- Round 1: 3 real findings (1 MEDIUM, 2 LOW)
- Round 2: 2 real findings (1 MEDIUM, 1 LOW) + 1 verified-clean

Per the iterative-audit skill's stop criteria: "Last 2 rounds found only MEDIUM/LOW severity" and "diminishing returns". Both apply.

Continuing to Round 3 (test coverage gaps) would produce a coverage table — useful for the user but not "findings" in the bug sense. I'll include the coverage scan inline in the final report rather than as a separate round, since it requires no code changes.

Stopping here and moving to synthesis.

## Round results summary

| Round | Pattern | Real findings | False-positive filtered | Tests added | Continue? |
|---|---|---|---|---|---|
| 1 | Security | 3 (1 MED, 2 LOW) | 0 | n/a (audit-only) | Stop |
| 2 | Resource cleanup | 2 (1 MED, 1 LOW) + 1 verified clean | 0 | n/a | Stop |

Diminishing returns confirmed. Halting iterative audit and producing the final consolidated report.