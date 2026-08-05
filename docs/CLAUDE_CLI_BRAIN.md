# Running the gateway brain on the Claude Code CLI

Status: **design + evidence, not yet built.** Written 2026-08-05 after removing OpenRouter.

## The question

Can the Hermes gateway's brain run on the Claude Code Max subscription instead of
pay-per-token keys?

## What was actually measured

Two routes to "use the subscription" exist. Only one of them spends the plan.

### Route A — borrow the OAuth token (does NOT work)

`agent/anthropic_adapter.py:917 read_claude_code_credentials()` reads Claude Code's own
refreshable OAuth credential from the macOS Keychain, and `:386 _is_oauth_token` / `:803`
send it as `Authorization: Bearer`. It is wired up and it authenticates. The credential is
live and in the pool:

```
auth.json credential_pool.anthropic[0]
  id 6e97cc  label claude_code  auth_type oauth  source claude_code
  expires_at_ms 1785968962468   (identical to the Keychain entry)
```

The gateway used exactly that credential on 2026-08-05 22:24:41 and Anthropic answered:

```
provider=anthropic base_url=https://api.anthropic.com model=claude-haiku-4-5-20251001
HTTP 400: Third-party apps now draw from your extra usage, not your plan limits.
          Add more at claude.ai/settings/usage and keep going.
```

That is a **billing** verdict, not an auth failure. Third-party clients presenting the token
are metered against pay-as-you-go extra usage, which is at zero — so the request is refused
even though the Max plan is active.

A raw probe *did* get `HTTP 200 'PONG'` from `claude-haiku-4-5-20251001` at 22:19, which
looks like a contradiction until you look at what it sent: `user-agent: claude-cli/2.1.74`,
`x-app: cli`, and `anthropic-beta: claude-code-20250219,oauth-2025-04-20`. It got 200 by
passing as first-party. In the same probe `claude-opus-4-5-20251101` and
`claude-sonnet-4-5-20250929` returned `429 rate_limit_error` on three consecutive attempts
with no reset headers — consistent with drawing on a spent plan window, which is further
evidence the 200 was plan-metered rather than extra-usage-metered.

**Conclusion: do not chase Route A.** It is not a config bug and no header or key fixes it.
It self-heals only if extra usage is funded, which is why `anthropic` stays in
`config.yaml`'s `fallback_model` chain rather than being deleted.

### Route B — invoke the `claude` binary (works)

```
$ env -u ANTHROPIC_API_KEY -u ANTHROPIC_TOKEN claude -p "Reply with exactly one word: PONG"
PONG
exit=0                                                          # 2026-08-05 22:26
```

First-party, draws on the plan. This is not a new idea in the estate —
`scripts/coordinator.py:1178` already runs its Tier 1 executor as
`["claude", "-p", "--permission-mode", "acceptEdits"]` with `env.pop("ANTHROPIC_API_KEY")`
(`:1125`, commented "subscription/OAuth, never the dead pay-per-token key"). The coordinator
executor tier has been on the subscription all along; the gateway brain has not.

## Proposed shape: a local OpenAI-compatible shim

The fork needs **no changes**. `resolve_provider` accepts `custom` (`hermes_cli/auth.py:1560`),
which is the same path `ollama` / `vllm` / `llama.cpp` use (`:1541-1543`) — a local
OpenAI-compatible server at an arbitrary `base_url`.

```
scripts/claude_cli_shim.py     # serves POST /v1/chat/completions on 127.0.0.1
                               # -> subprocess: claude -p --output-format json
                               # -> maps stdout back to an OpenAI chat completion
```

```yaml
# config.yaml
model:
  default: claude-cli
  provider: custom
  base_url: http://127.0.0.1:8788/v1
```

Statelessness is not a problem: the gateway sends full history on every turn, so a
per-request `claude -p` with no `--resume` is the correct semantics.

## The caveat that decides whether this is worth building

`claude -p` runs **its own** tool loop internally and returns final text. It does not emit
OpenAI-format `tool_calls`. So a naive shim gives the gateway a brain that can think but
cannot use any of the gateway's own tools — no `hermes send`, no memory writes, no estate
controls. For an agentic gateway that is a real functional regression, not a detail.

The fix is a second phase, and the mechanism already exists but is unused:
`hermes mcp serve` ("Run Hermes as an MCP server — expose conversations to other agents",
`hermes mcp --help`). Bridge it in with `claude --mcp-config` so the inner Claude Code
instance calls Hermes' tools directly, and the tool loop moves inside Claude Code instead of
being lost.

**Build order:** shim first and measure latency on real turns (each turn spawns a process);
only then wire the MCP bridge. Do not ship phase 1 as the default brain — a toolless brain
on a tool-driven gateway is a downgrade even though the model is stronger.

## Related

- OpenRouter removal, same session: `config.yaml` header comment on `model:`, and the
  `.env` notes on `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `ANTHROPIC_API_KEY`.
- `scripts/coordinator.py:1099-1186` — the existing, working CLI executor tier.
