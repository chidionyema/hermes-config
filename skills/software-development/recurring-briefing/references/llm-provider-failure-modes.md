# LLM Provider Failure Modes — Detection and Response

A class-level reference for the failure modes that LLM-driven cron jobs exhibit when the upstream provider rejects the request. Every recurring briefing / strategist-audit / project-health-audit that touches an LLM-driven cron should consult this file before declaring the cron "broken."

## Why this exists

Cron jobs that call `hermes run` (or equivalent LLM dispatcher) fail in one of two distinct ways:

1. **Script-defect failure** — the Python or shell script has a bug (bad path, missing var, etc.). The fix is in the cron prompt or the script.
2. **Provider-rejection failure** — the script ran correctly, the request went out, and the provider rejected it (billing, auth, rate limit, model unavailable). The fix is `needs_human` (money/auth) or wait/retry.

Type-2 failures masquerade as Type-1 because the cron job surfaces only `TimeoutError: waiting for stream response (Ns, no chunks yet)` — it cannot see the upstream HTTP status. This file is the catalog of Type-2 signatures and the protocol for distinguishing them.

## Failure mode catalog

### FM-1: HTTP 402 — Insufficient Balance

**Signature in `logs/agent.log`:**
```
Streaming failed before delivery: Error code: 402 - {'error': {'message': 'Insufficient Balance', 'type': 'unknown_error', 'param': None, 'code': 'invalid_request_error'}}
```

**Signature in cron `last_error`:**
```
TimeoutError: Cron job 'X' idle for 936s (limit 600s) — last activity: waiting for stream response (151s, no chunks yet)
```

**Root cause:** Upstream provider account has no balance, or the model is on a paid tier and the key is on a free tier.

**Detection protocol:**
```bash
grep -E "Insufficient Balance|HTTP 402|402 -" /Users/chidionyema/.hermes/logs/agent.log | tail -3
```

**Fix:** `needs_human`. Top up provider balance OR switch default model in `~/.hermes/config.yaml` (e.g. `deepseek-v4-pro` → `MiniMax-M3, provider: minimax`).

**Watchdog treatment:** Emit a single `CREDITS_ERROR` fingerprint per affected job per cycle. Do NOT re-fire `CRON_ERROR` every 15 minutes — it generates hundreds of alerts with zero resolution path. Reference implementation: `~/.hermes/scripts/watchdog.py` lines ~102-135 (added 2026-07-02).

**Matched in production:** 2026-07-02 strategist-audit — morning-briefing and daily-strategist-audit both hung at 9am / 8am for 9 days before audit. 1293 `CRON_ERROR` lines in watchdog.jsonl, single root cause.

### FM-2: HTTP 401 — Unauthorized

**Signature:** `Authentication credentials not found` or `Invalid API key`.

**Root cause:** `DEEPSEEK_API_KEY` (or equivalent) in `~/.hermes/.env` is missing, expired, or revoked. Note: `~/.config/llm/secrets.sh` is NOT loaded by Hermes runtime — only `~/.hermes/.env` is.

**Detection protocol:**
```bash
grep -E "401 Unauthorized|Invalid API key|Authentication credentials" /Users/chidionyema/.hermes/logs/agent.log | tail -3
```

**Fix:** `needs_human`. Re-issue API key, update `~/.hermes/.env`.

**Watchdog treatment:** Same as FM-1 — single `AUTH_ERROR` per cycle, not `CRON_ERROR` re-fire.

### FM-3: HTTP 429 — Too Many Requests

**Signature:** `Rate limit reached` or `Requests per minute exceeded`.

**Root cause:** Provider rate-limit hit, or multiple crons calling the same model simultaneously (cron thundering herd).

**Detection protocol:**
```bash
grep -E "429|Too Many Requests|rate limit" /Users/chidionyema/.hermes/logs/agent.log | tail -3
```

**Fix:** Either throttle (add jitter to cron schedules) OR upgrade provider tier. Often self-resolves within 1 minute.

**Watchdog treatment:** Different from FM-1 — rate limits ARE transient and self-resolve. The existing `Script timed out after` exclusion in `watchdog.py` already covers this case if the request times out before the 429 fires. If the 429 fires AFTER the timeout, surface as `RATE_LIMITED` once per affected job.

### FM-4: Model not found / model deprecated

**Signature:** `The model 'X' does not exist or you do not have access to it` or `Model not found`.

**Root cause:** Provider removed the model, or the configured model name has a typo (`deepseek-v4-pro` vs `deepseek-chat` vs `deepseek-reasoner`).

**Detection protocol:**
```bash
grep -E "model.*does not exist|model not found|Model not found" /Users/chidionyema/.hermes/logs/agent.log | tail -3
```

**Fix:** Update `model: <name>` in `~/.hermes/config.yaml` to a current model name. Can be auto-fixed if the catalog of valid models is known; otherwise `needs_human`.

### FM-5: Network stall / DNS failure

**Signature:** `[Errno 8] nodename nor servname provided, or not known` or `Connection refused` or `Connection reset by peer`.

**Root cause:** DNS failure, VPN drop, provider outage, local network issue.

**Detection protocol:**
```bash
grep -E "Errno 8|Connection refused|Connection reset|DNS" /Users/chidionyema/.hermes/logs/agent.log | tail -3
```

**Fix:** Often self-resolves. If persistent, check DNS (`dig api.deepseek.com`), VPN status, provider status page. NOT a script defect.

## Detection protocol — pre-flight check

Before recommending any cron-edit fix for an LLM-driven cron that shows `TimeoutError`, run this:

```bash
JOB_NAME="morning-briefing"  # or whichever

# 1. Get the cron job's last_error
python3 -c "
import json
data = json.load(open('/Users/chidionyema/.hermes/cron/jobs.json'))
jobs = data.get('jobs', data) if isinstance(data, dict) else data
if isinstance(jobs, dict): jobs = list(jobs.values())
for j in jobs:
    if isinstance(j, dict) and j.get('name') == '$JOB_NAME':
        print(j.get('last_error', '(none)'))
"

# 2. Search agent.log for any provider rejection in the last hour
grep -E "Insufficient Balance|HTTP 402|401 Unauthorized|429|model.*does not exist|Connection refused" \
  /Users/chidionyema/.hermes/logs/agent.log | tail -5

# 3. Check if the provider itself is healthy
curl -s -o /dev/null -w "%{http_code}" https://api.deepseek.com/v1/models  # adapt per provider
```

If step 2 hits, classify by FM type and surface as `needs_human`. If step 2 misses but the cron is still failing, it IS a script defect.

## Watchdog classifier pattern (reference)

This is the pattern that should be in `~/.hermes/scripts/watchdog.py` (added 2026-07-02):

```python
# Inside check_cron_health, where each job's last_error is classified:
err = str(j.get("last_error") or "")

# Type-1: scheduler kill (already excluded — transient overload class)
if "Script timed out after" in err:
    continue

# Type-2: provider rejection — distinguish by signature, emit once per cycle
is_credits = any(token in err for token in ("Insufficient Balance", "402", "Payment Required"))
is_stream_stall = "waiting for stream response" in err and "no chunks yet" in err
if is_credits or is_stream_stall:
    # Cross-reference agent.log for the underlying HTTP status if it's a stream stall
    upstream_cause = ""
    if is_stream_stall:
        try:
            _r = subprocess.run(
                ["grep", "-E", "Insufficient Balance|HTTP 402|402 -", "-m", "3", "logs/agent.log"],
                capture_output=True, text=True, timeout=5,
            )
            if _r.stdout.strip():
                upstream_cause = " — upstream agent.log shows provider billing rejection"
        except Exception:
            pass
    # Emit single CREDITS_ERROR fingerprint, not CRON_ERROR re-fire
    credit_alert = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "type": "CREDITS_ERROR",
        "message": f"CREDITS_ERROR: {name} provider rejected request (likely billing){upstream_cause}: {err[:200]}",
        "job": name,
        "status": "open",
        "healthy": False,
    }
    try:
        with open(ALERT_LOG, "a") as _f:
            _f.write(json.dumps(credit_alert) + "\n")
    except Exception:
        pass
    continue
# Else: real script-defect failure, emit CRON_ERROR as normal
alerts.append(f"CRON_ERROR: {name} errored: {err[:80]}")
```

The `is_stream_stall + agent.log cross-reference` is the key pattern. The cron surfaces only the TimeoutError; the upstream HTTP status lives in `agent.log`. Bridging the two is what makes billing-rejection failures detectable from cron state alone.

## Why this file exists separately from the SKILL.md pitfall

The SKILL.md has the pitfall in compressed form. This reference is the **catalog** with full grep patterns, full root-cause analysis, and the reference watchdog implementation. Future audits loading `recurring-briefing` will see the pitfall headline and pull this file when they need to execute the detection protocol.

## When to update this file

- When a new provider failure mode is encountered (add an FM-N entry).
- When the watchdog classifier pattern changes (update the reference implementation).
- When the cross-reference grep pattern misses a real failure (broaden the grep).
- When `agent.log` location changes (update paths).

Last matched in production: 2026-07-02 (DeepSeek 402 — see audit report `~/.hermes/reports/strategist-audit-2026-07-02.md`).