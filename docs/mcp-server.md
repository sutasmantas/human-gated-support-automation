# Relay MCP server

Relay exposes its governed workflow through the official MCP Python SDK v2.
MCP is a transport and typed adapter, not a second execution engine: the
existing registry, approval, receipts, retries, dead-letter state, and audit
events remain authoritative.

## Tools

| MCP tool | Behavior | Side-effect boundary |
| --- | --- | --- |
| `relay_list_governed_tools` | Returns the internal tool schemas and risk classes. | Direct read. |
| `relay_list_runs` | Returns bounded recent run summaries. | Direct read. |
| `relay_get_run` | Returns one ticket, its tool calls, and audit events. | Direct read. |
| `relay_wait_for_run` | Cancellably waits up to 30 seconds for a terminal state. | Direct read; no action execution. |
| `relay_propose_support_run` | Validates and plans a deterministic support run under a stable idempotency key. | The customer lookup runs; every write/irreversible call is persisted as `awaiting_approval`. |

There is deliberately no MCP approval tool. An agent cannot approve its own
proposal. A human uses the existing Relay UI or
`POST /api/tickets/{ticket_id}/approve`; execution then follows the existing
receipt, attempt, retry, failure, and audit path.

## Stdio quickstart and Inspector

```bash
python -m pip install -e ".[dev]"
python -m support_desk.mcp_server
```

Desktop/IDE hosts can use [`mcp.example.json`](../mcp.example.json). The
official Inspector 2.0.0 CLI provides a second implementation of the client:

```bash
npx -y @modelcontextprotocol/inspector@2.0.0 --cli \
  --config mcp.example.json --server relay --method tools/list --format json

npx -y @modelcontextprotocol/inspector@2.0.0 --cli \
  --config mcp.example.json --server relay --method tools/call \
  --tool-name relay_list_runs --tool-args-json '{"limit":5}' --format json
```

Inspector 2.0.0 requires Node 22.19 or later. Stdio authentication is the
launching process and local OS boundary; bearer authentication does not apply
to a child-process pipe.

## Streamable HTTP

The no-key development server binds only to loopback:

```bash
python -m support_desk.mcp_server --transport http
```

Clients connect to `http://127.0.0.1:8001/mcp`. The official SDK's default
transport security accepts loopback Host/Origin values and rejects invalid
Host or Origin headers before an MCP tool executes.

Non-loopback binding is fail-closed. It requires every setting below:

```dotenv
SUPPORT_MCP_HOST=0.0.0.0
SUPPORT_MCP_ALLOW_NETWORK=true
SUPPORT_MCP_ALLOWED_HOSTS=mcp.example.com,mcp.example.com:*
SUPPORT_MCP_ALLOWED_ORIGINS=https://agent.example.com
SUPPORT_MCP_AUTH_MODE=static-bearer
SUPPORT_MCP_AUTH_TOKEN_REF=env:RELAY_MCP_TOKEN
SUPPORT_MCP_ISSUER_URL=https://identity.example.com
SUPPORT_MCP_RESOURCE_SERVER_URL=https://mcp.example.com/mcp
SUPPORT_MCP_REQUIRED_SCOPES=relay:tools
```

The token is resolved from the named environment variable on verification and
is never returned in tool output or audit data. The SDK publishes protected
resource metadata and requires the configured scope. This static verifier is a
bounded deployment/test seam; a real customer deployment should replace it
with JWT validation or RFC 7662 introspection against its identity provider.
Relay does not issue tokens or implement an authorization server.

## Verification evidence

`tests/test_mcp_server.py` uses the official SDK's in-memory client and a real
Streamable HTTP socket. It proves:

- structured schemas and structured results;
- malformed-argument rejection and missing-run tool failure;
- direct reads and cancellable bounded waiting;
- one proposal under duplicate calls and rejection of key reuse with a changed
  payload;
- zero external effects before approval and one effect per action after the
  existing approval path;
- localhost-only configuration, invalid Host/Origin rejection, missing/wrong
  bearer rejection, and an authenticated MCP discovery/read call.

The external Inspector gate launches `python -m support_desk.mcp_server` as a
real stdio subprocess. Its proposal result showed one completed read and three
`awaiting_approval` writes; the SQLite audit showed one proposal and zero
receipts, billing holds, case events, or notification writes.

## Limitations

- SQLite and the in-process executor remain a single-process demo boundary.
- The proposal-key mapping prevents sequential duplicate workflows; it is not
  a distributed concurrency or exactly-once protocol.
- Static bearer auth proves the HTTP resource-server boundary but is not a
  production identity-provider integration.
- The stdio server trusts the local launching process, as defined by MCP.
- No MCP App UI, resource, prompt, sampling, elicitation, or multi-agent layer
  is added; none is needed for this evidence slice.
