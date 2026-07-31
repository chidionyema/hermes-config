# Claude Code remote — phone loop + resilience (LIVE)

Shipped: Telegram → durable `code:telegram` coordinator tasks via `claude -p` → agy → chat fallback.

## Exact phone loop (seamless)

1. **Assign (zero ceremony)**
   - `Otto code <task>` / `cc <task>` / `Otto, code: <task>`
   - Natural: `fix the login bug in prospector` / `implement X on POPDD`
2. **Living progress** — one Telegram message edited in-place (`progress_msg_id`); no per-step spam.
3. **Steer / cancel / pause** — buttons on the card (`estate:cancel|pause_task|steer_prompt`) or:
   - `Otto steer <id> <instruction>`
   - `cancel <id>` / `pause <id>` / `task <id>`
4. **`/panel`** — when a coding run is active (and no higher money/identity fence), primary CTA deep-links to that run. Code fences deep-link to the task APPROVE card.
5. **Done** — one receipt (what / files / proof id) on the same progress message, then quiet.

## Resilience guarantees (live)

| Guarantee | Mechanism |
|-----------|-----------|
| Gateway/coordinator restart | Same task row + `progress_msg_id`; executor pool re-submits once (no second task) |
| Telegram blip / duplicate assign | Idempotent start: same body within 10m resumes existing run |
| Quota / rate-limit | Immediate CB honesty on card; queue + fallback path; never fake "working" tools |
| Executor crash | One auto-retry (`exec_crash_retry` event) next tick; then escalate with Retry/Cancel CTA |
| Progress edit failure | `progress_outbox` retry (≤5 attempts) drained every tick |
| Money/identity | Fence before mutate; never silent; APPROVE required |
| Idempotent buttons | Estate `request_id` store |

## Credential / ops gaps (honest)

- Claude quota CB may force agy/chat fallback
- `gh auth login` if CI panel needed
- Cron Topics / Signal APPROVE / optional NTFY unchanged
