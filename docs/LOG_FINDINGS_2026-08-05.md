# What the last hour of logs says — 2026-08-05 21:50–22:50

Method: `~/.hermes/logs/{errors,gateway.error,agent}.log`, lines timestamped inside the
window, normalised (ids and digits collapsed) and bucketed by frequency. Every number below
is a count from that pass or a `grep -c`; every code claim carries a `file:line`.

Reference point for "before/after": the gateway restarted at **22:27:45**
(`gateway.log`, `gateway.operator_shell.preflight: preflight: warmup started`). The
OpenRouter fix (`2f06b90`) landed before it.

---

## 0. The OpenRouter purge held

Last openrouter mention anywhere in `errors.log` is **22:20:54**, seven minutes *before* the
restart:

```
7148:2026-08-05 22:20:54,508 WARNING agent.conversation_loop: API call failed (attempt 1/3)
  error_type=AuthenticationError provider=openrouter base_url=https://openrouter.ai/api/v1
  model=anthropic/claude-opus-4-20250514 summary=HTTP 401: Missing Authentication header
```

Zero after. Note for the next person auditing this: `awk '$0 >= "2026-08-05 22:27:45"'` is
**not** a safe post-restart filter — continuation lines have no leading timestamp and sort
above the cutoff lexicographically ("O" > "2"), which produced two false "post-restart
openrouter" hits before `grep -n` with real timestamps settled it.

---

## 1. The brain emits a duplicate `patch` call on *every* turn — 58 in the hour

```
$ grep -hE '2026-08-05 2[12]:' errors.log | grep -c 'Removed duplicate tool call: patch'
58
```

There were also exactly 58 `agent.conversation_loop: API call #N: model=MiniMax-M3
provider=minimax` lines in the same window. **One duplicate per API call.** And it is
specific to `patch` — across the whole file the dedup counter reads:

```
58 patch     3 web_search     2 terminal
```

`run_agent` catches it, so nothing breaks. The cost is silent: every patch is serialised
twice into the output stream, on a paid MiniMax turn, and the model's next-turn context
carries both. A tool that is duplicated 100% of the time is not the model being sloppy —
that is a schema or streaming-parse defect in how the `patch` tool is presented or read
back. **Highest-value thing on this list**: it is a per-turn tax on the busiest tool.

**Next check:** dump one raw MiniMax response containing a patch call and see whether the
duplicate exists on the wire or is created by the parser.

## 2. Permanent 400s are retried as if they were transient

```
2026-08-05 22:37:24,509 WARNING agent.conversation_loop: API call failed (attempt 1/3)
  error_type=BadRequestError provider=anthropic model=claude-fable-5
  summary=HTTP 400: Third-party apps now draw from your extra usage, not your plan limits.
2026-08-05 22:37:25,109 INFO  agent.chat_completion_helpers: Fallback activated:
  claude-fable-5 → claude-haiku-4-5-20251001 (anthropic)
2026-08-05 22:37:27,600 WARNING agent.conversation_loop: API call failed (attempt 1/3)
  error_type=BadRequestError provider=anthropic model=claude-haiku-4-5-20251001
  summary=HTTP 400: Third-party apps now draw from your extra usage, not your plan limits.
```

`gateway.error.log` carries **69** `attempt 2/3` lines. This particular 400 is a billing
verdict — it is permanent until extra usage is funded, and *no* model on the anthropic
provider will behave differently, which is why the fallback to haiku failed 3 seconds later
with the identical body.

**Improvement:** classify `"draw from your extra usage"` (and 400s generally, absent an
explicit retryable marker) as non-retryable, and circuit-break the whole **provider** rather
than trying the next model on it. Saves ~3s and 2 wasted requests per affected turn, and
gets the user a working answer sooner.

## 3. The auxiliary health-marker reports a cause it does not know

`agent/auxiliary_client.py:2306` hardcodes the reason string:

```python
logger.warning(
    "Auxiliary: marking %s unhealthy for %ds (payment / credit error). "
    "Subsequent auxiliary calls will skip it until %s.", ...)
```

…but `:1600-1603` calls it for something else entirely:

```python
"Auxiliary Nous client unavailable: no Nous authentication found (run: hermes auth)."
_mark_provider_unhealthy("nous", ttl=60)
```

So a *missing credential* is logged as a *payment error*. That is the same class of defect
as the fence grep: the message asserts a cause instead of reporting one. In the 22:20 window
this fired 8 times for nous and 8 for openrouter, and the same provider was marked unhealthy
**four times inside 1.2 seconds** (22:20:22,120 / ,176 / 22:20:23,315 / ,342) — concurrent
callers each re-marking, so the 60s TTL suppresses the *calls* but not the *noise*.

**Improvement:** pass the cause in (`reason="auth_missing" | "payment" | "http_5xx"`), and
give auth-missing an effectively infinite TTL — retrying an unconfigured provider every 60s
forever is pure waste. No auxiliary call has run since the 22:27 restart, so this is proven
in the code and in pre-restart logs, not proven live post-restart.

## 4. Cheap noise worth clearing

- `gateway.platforms.telegram: [Telegram] Telegram flood control, waiting N.Ns` — 4 in the
  hour. The gateway is being rate-limited by Telegram; batching or a send-side token bucket
  would remove the stall.
- `hermes.lint.lsp: lsp[pyright] spawn/initialize failed for ~/.hermes/hermes-agent:
  TimeoutError` (22:21:46). The lint path is silently degraded — findings that depend on
  pyright are not being produced.
- `gateway.source_watch: source changed and settled — restarting` fired 3 times in the hour.
  Every edit to gateway source bounces the live gateway 20s later, mid-conversation. That is
  the design, but it means **an agent editing gateway/ during a live session restarts
  production**; worth a guard that defers the restart while a turn is in flight.

---

## Ranked

1. **Duplicate `patch` on every turn** (§1) — 100% hit rate, paid, silent.
2. **Retrying permanent 400s** (§2) — user-visible latency on every anthropic attempt.
3. **Auxiliary marker lies about the cause** (§3) — cheap fix, removes a whole class of
   misleading log evidence.
4. Telegram flood control, dead pyright, restart-mid-turn (§4).
