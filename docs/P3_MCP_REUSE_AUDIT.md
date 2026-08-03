# Relay P3 MCP component comparison

Date: 2026-08-03

This comparison closes the mandatory GitHub/component gate before Relay MCP
implementation. License was not used as a selection filter; the decision is
based on fit, maintained protocol coverage, integration size, and executable
test surfaces.

## Decision

Adopt the official MCP Python SDK v2 and its server, transports, transport
security, resource-server auth seam, structured output, and in-memory test
client. Pin Relay to the stable v2 major with `mcp>=2.0,<3`.

Use the official Inspector package at `@modelcontextprotocol/inspector@2.0.0`
for the external no-key stdio smoke. Keep Relay's approval, idempotency, retry,
dead-letter, and audit mechanisms as the domain execution layer; MCP is only a
transport and typed adapter over them.

## Compared foundations and components

| Candidate | Pinned revision/version | Decision | Reason |
| --- | --- | --- | --- |
| [Official MCP Python SDK v2](https://github.com/modelcontextprotocol/python-sdk) | tag `v2.0.0`, commit `6f69a3758ebf2ee55ce050f58b470ce11af71133` | `adopt` | Current stable line as of this audit. It provides typed tool schemas and structured results, stdio and Streamable HTTP, localhost-safe Host/Origin validation, OAuth resource-server hooks, and an in-memory client. These exactly match P3 without a custom protocol layer. |
| [Official MCP Python SDK v1](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x) | tag/branch `v1.29.0`, commit `98b7159cb89274964055d2c016e3360a551280d0` | `reject` | v1 is maintenance-only after stable v2. Starting new work there would create an immediate migration task and miss the current 2026-07-28 protocol path. |
| [FastMCP](https://github.com/jlowin/fastmcp) | main commit `022547ad8c957753d0b5a09290a4be345d3f01d2` | `reject` | Its composition, OpenAPI conversion, proxying, and broader client framework are useful but larger than Relay's bounded transport need. The official SDK now covers every required P3 surface directly. |
| Custom JSON-RPC/ASGI transport | Relay base `7d4711e` | `reject` | Reimplementing negotiation, schemas, cancellation, transport framing, Host/Origin defense, auth discovery, and Inspector compatibility would be integration risk with no portfolio gain. |
| [Official MCP Inspector](https://github.com/modelcontextprotocol/inspector) | npm `2.0.0`; `v2/main` commit `07a2b4bdfda06087cbdf8863d990a0c32f8009c3` | `adopt for external verification` | The published CLI exercises tool discovery and calls over a real stdio subprocess. It is evidence independent of the Python SDK's in-memory client. |

## Refit versus custom boundary

- **Adopt:** SDK `MCPServer`, decorators, Pydantic-generated input/output
  schemas, `Client`, stdio, Streamable HTTP, `TransportSecuritySettings`,
  `TokenVerifier`, and `AuthSettings`.
- **Refit:** wrap Relay's ticket/run reads and deterministic planning as MCP
  tools; return typed summaries; expose the existing governed internal tool
  catalog as read-only metadata.
- **Custom only where domain-specific:** one idempotent proposal key mapping
  and the adapter from an MCP proposal to Relay's existing pending actions.
  External writes still execute only through Relay's existing human approval,
  receipt, retry, failure, and audit path.

## Required verification shaped by the comparison

- SDK in-memory tests: structured inputs/outputs, malformed arguments, direct
  reads, proposal-only writes, duplicate proposal keys, tool failures, and
  cancellation of a bounded read wait.
- Real Streamable HTTP tests: default localhost Host allowlist, invalid Origin,
  explicit bearer authentication, and authenticated tool discovery/call.
- Official Inspector `2.0.0`: launch Relay as a stdio subprocess, list tools,
  call a no-key read, and create one proposal whose writes remain unexecuted.

The implementation must not add an MCP approval tool. Approval remains an
operator action through Relay's existing API/UI, so an MCP model cannot approve
its own proposed external side effects.
