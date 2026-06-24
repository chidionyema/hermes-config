# Checkpoint — sentinel-loop ship effort (2026-06-23, increment 3 DONE)

## What was built (C3 + C4 + H2 + H4 + H5 + H6 + H7)

### C3 — Entry points (the thing now runs)
- `sentinel/cockpit/runner.py` — preflight gate (dev warns, prod raises on missing secrets), main() normalises localhost→127.0.0.1 (H5), runs uvicorn
- `sentinel/coordinator.py` — main() builds FiscalSentry with explicit HERMES_TOKEN_BUDGET (NEVER None — C9 closed), run() provides finite-iteration testability
- `sentinel/watchdog.py` — same pattern; run() calls health_check_all() + sentry poll each tick
- `tests/test_entry_points.py` (10 tests), `tests/test_runner.py` (7 tests)

### C4 — Reachability
- All 6 plists: ProgramArguments→python3 -m sentinel.<mod>, WorkingDirectory correct, C1-safe labels
- New `launchd/ai.hermes.cockpit.plist` for the cockpit server
- `scripts/setup_webhook.sh` — tunnel discovery + setWebhook with secret_token + verify
- All plists plutil -lint OK

### H4 — MarkdownV2 escape
- `sentinel/gateway/telegram_bridge.py` — escape_markdown_v2() at HTTPTransport.send layer
- parse_mode changed from "Markdown" to "MarkdownV2"
- `tests/test_h4_escape.py` (3 tests)

### H6 — Callback_data sanitize
- `sentinel/cockpit/ui_engine.py` — sanitize_callback_token() applied in project buttons, monitor ingestion, github processor
- `tests/test_h6_sanitize.py` (6 tests)

### H7 — Severity trust
- `monitor_ingestion.should_override()` validates severity against {critical,warning,info}

### H2 — Sandbox path validation
- `sandbox_core.SandboxCore.bootstrap()` validates target exists + is git repo before subprocess

### H5 — localhost→127.0.0.1
- Normalised in runner.main() at bind time (perimeter unchanged — held-out test)

### OpenRouter
- REMOVED from live gateway plist, .env, config.yaml
- Replaced with DeepSeek (DEEPSEEK_API_KEY)
- Gateway reloaded — running under new pid

## Proof (NOT assertion — run these yourself):

```bash
cd ~/Documents/code/sentinel-loop

# Integrity gate
bash scripts/check-integrity.sh           # 6/6 PASS

# Visible tests
python3 -m pytest -q -m "not slow"        # 180 passed

# Held-out tests
python3 -m pytest verify/ -q              # 62 passed

# Plist validity
for f in launchd/*.plist; do plutil -lint "$f"; done  # 6/6 OK
```

## What's left (pre-cutover)
1. Start a tunnel (cloudflared tunnel --url http://127.0.0.1:8800)
2. Run scripts/setup_webhook.sh to register with Telegram
3. Prove end-to-end: real button click → real command executed → budget trip enforced
4. Cutover: flip @Ottototbot from polling to webhook
