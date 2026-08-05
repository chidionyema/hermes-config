# Running the gateway brain on the Claude Code CLI

Status: **route proven end-to-end by measurement 2026-08-05; not yet wired into the gateway.**

## The question

Can the Hermes gateway's brain run on the Claude Code Max subscription instead of
pay-per-token keys, without losing the gateway's tools?

Yes. The path is ACP + MCP, and every link below was measured, not reasoned about.

## Route A — borrow the OAuth token (dead end, do not retry)

`agent/anthropic_adapter.py:917 read_claude_code_credentials()` reads Claude Code's
refreshable OAuth credential from the macOS Keychain and `:386 _is_oauth_token` / `:803`
send it as `Authorization: Bearer`. It is wired up, and it authenticates. Using it
(`auth.json` credential_pool.anthropic id `6e97cc`, `auth_type=oauth`, `source=claude_code`,
`expires_at_ms` identical to the Keychain entry), the API answered at 22:24:41:

```
provider=anthropic base_url=https://api.anthropic.com model=claude-haiku-4-5-20251001
HTTP 400: Third-party apps now draw from your extra usage, not your plan limits.
          Add more at claude.ai/settings/usage and keep going.
```

A **billing** verdict, not an auth failure. No header or key fixes it; it clears only if
extra usage is funded. That is why `anthropic` stays in `config.yaml`'s `fallback_model`
chain (self-heals if funded) rather than as primary.

**Trap:** a hand-rolled probe of the same token *did* return `HTTP 200 'PONG'` — but only
because it sent `user-agent: claude-cli/2.1.74`, `x-app: cli` and
`anthropic-beta: claude-code-20250219,oauth-2025-04-20`, i.e. it passed as first-party. A
200 from a bespoke probe does **not** predict what the integration will do.

## Route B — drive the real binary over ACP (works)

`@agentclientprotocol/claude-agent-acp` (npm, installed globally; the older
`@zed-industries/claude-code-acp` is the deprecated name) wraps Claude Code in the Agent
Client Protocol. The fork already speaks ACP: `agent/copilot_acp_client.py` is 679 lines of
"OpenAI-compatible shim that forwards Hermes requests to `copilot --acp`", and the binary is
env-overridable — `HERMES_COPILOT_ACP_COMMAND` (`:56`) and `HERMES_COPILOT_ACP_ARGS` (`:64`).

Measured against `claude-agent-acp` with the fork's exact JSON-RPC sequence
(`initialize` → `session/new` → `session/prompt`, `copilot_acp_client.py:543-586`):

```
initialize   OK   protocolVersion 1, mcpCapabilities {http: true, sse: true}
session/new  OK   sessionId returned
session/prompt    stopReason end_turn, totalTokens 104691
```

No 400. It is the real binary running first-party, so it **draws on the Max plan** — the
same property `scripts/coordinator.py:1178` already relies on for its Tier 1 executor
(`["claude","-p","--permission-mode","acceptEdits"]`, `env.pop("ANTHROPIC_API_KEY")` at
`:1125`). It also has full Claude Code capability: the first probe ran a live web search and
returned sourced results.

## Why the existing shim's tool contract does NOT work with Claude Code

`_format_messages_as_prompt` (`:128`) describes the OpenAI `tools` array **in prose** and
instructs the agent to emit `<tool_call>{...}</tool_call>` blocks, which
`_extract_tool_calls_from_text` (`:227`) parses back out. Copilot complies. Claude Code
does not, for two independent reasons it stated itself when probed:

1. It checks its actual tool list and refuses to fabricate:
   > "my tool list has no weather function ... So I can't call it, and I won't emit a fake
   > `<tool_call>` block pretending I did."
2. Even when it does call a tool, the call never appears as text:
   > "I emit tool calls in this harness's native format, not `<tool_call>{...}</tool_call>`
   > OpenAI-shaped blocks. If Hermes needs OpenAI-shaped function calls, that translation
   > has to happen in the ACP bridge — I can't produce them as raw text and have them
   > execute."

Claude Code emits tool calls as ACP `session/update` events. `_extract_tool_calls_from_text`
can therefore **structurally never** see them. This is not a prompt-tuning problem.

## The fix that was measured: give it the tools for real over MCP

`hermes mcp serve` is already in the CLI and was unused. Probed directly over stdio MCP it
answers `initialize` in **5.9s** and `tools/list` returns **10 tools**:

```
conversations_list  conversation_get  messages_read   attachments_fetch  events_poll
events_wait         messages_send     channels_list   permissions_list_open
permissions_respond
```

ACP's `session/new` takes an `mcpServers` array. Passing Hermes' server there:

```json
{"name": "hermes", "command": "~/.local/bin/hermes",
 "args": ["mcp", "serve", "--accept-hooks"],
 "env": [{"name": "HERMES_ACCEPT_HOOKS", "value": "1"}]}
```

Claude Code then reports all ten in its **real** tool list:

```
mcp__hermes__attachments_fetch      mcp__hermes__channels_list
mcp__hermes__conversation_get       mcp__hermes__conversations_list
mcp__hermes__events_poll            mcp__hermes__events_wait
mcp__hermes__messages_read          mcp__hermes__messages_send
mcp__hermes__permissions_list_open  mcp__hermes__permissions_respond
```

Registration is **asynchronous**. Prompting immediately, or after a 3-4s warm-up turn, gets
"the hermes MCP server is still connecting — its tools are not yet available". After a 30s
wait all ten are present. Irrelevant for a long-lived gateway session; fatal for a
spawn-per-turn design, and the reason `--accept-hooks` matters (without it the server can
block on a hook prompt with no TTY).

## Two designs — pick B

**A. Claude Code as a completion endpoint.** Keep the gateway's tool loop; make the bridge
translate ACP tool-call events into OpenAI `tool_calls` and feed results back. Requires
editing `_handle_server_message` in the fork. Works against the grain: Claude Code wants to
execute, and is being asked to propose and wait.

**B. Claude Code as the agent.** Hand it Hermes' tools via MCP (proven above) and let it run
its own loop. The gateway keeps inbound routing, session/history and delivery; the reasoning
and tool execution move inside Claude Code. No prompt contract, no fabrication risk, no
translation layer. `messages_send` + `channels_list` mean it can already reply on its own.

B is with the grain and needs no OpenAI-shape translation at all. The only fork change is
`copilot_acp_client.py:563`, which hardcodes `"mcpServers": []` — it must pass the Hermes
server through.

## Build order

1. Parameterise `mcpServers` in `_run_prompt` (currently hardcoded `[]` at `:563`).
2. Register a `claude-acp` provider profile mirroring `plugins/model-providers/copilot-acp/`
   (35 lines, `auth_type="external_process"`), pointing at `claude-agent-acp`.
3. Hold the ACP session open across turns so the 30s MCP registration is paid once.
4. Measure per-turn latency on real traffic before making it the default brain.

Do not skip step 3 — a spawn-per-turn design pays the registration cost every turn and will
intermittently run with no tools at all, which is worse than the current MiniMax brain.

## Related

- OpenRouter removal, same session: commit `2f06b90`, and the `config.yaml` header comment
  on `model:`.
- `scripts/coordinator.py:1099-1186` — the existing, working CLI executor tier.
