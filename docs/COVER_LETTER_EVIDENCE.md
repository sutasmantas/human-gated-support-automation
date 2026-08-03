# Relay cover-letter evidence ledger

Last updated: 2026-08-03

## Referenceable outcome

Relay now demonstrates a governed agent/workflow outcome: a deterministic
planner reads a customer record through a typed read-only tool, proposes bounded
local and HTTP actions, exposes raw write arguments for human approval, executes
approved actions with idempotent receipts and classified retry behavior, and
persists enough call/event state to replay the lifecycle. The entire path runs
without credentials against a local HTTP fake.

The same governed boundary is now available through the official MCP Python
SDK v2 over stdio and Streamable HTTP. MCP clients can read schemas/runs and
create idempotent proposals, but cannot approve their own writes.

Use only the claims below. They describe implemented behavior, not client
results, production scale, or a named provider integration.

## Claim ledger

| Job family | Defensible concise claim | Exact implementation evidence | Exact test/demo evidence | Honest boundary |
| --- | --- | --- | --- | --- |
| AI agent / tool calling | “I built a bounded tool-calling runtime with registered JSON Schemas, runtime argument validation, read/write risk classes, approval before side effects, a deterministic no-key planner, an optional OpenAI-compatible adapter, and an official-SDK MCP surface over stdio and Streamable HTTP.” | `support_desk/tools.py`; `support_desk/store.py`; `support_desk/mcp_server.py`; `support_desk/config.py` | `tests/test_agent_tools.py`; `tests/test_mcp_server.py`; official Inspector 2.0.0 commands in `docs/mcp-server.md`; `python -m support_desk.demo_agent` | The OpenAI-compatible contract is fixture-tested, not a credentialed model evaluation. MCP exposes one bounded workflow, not multi-agent orchestration. |
| MCP server / governed agent tools | “I exposed typed, structured MCP tools over stdio and Streamable HTTP while keeping external writes as idempotent Relay proposals that only the separate human approval API can execute. The HTTP path is localhost-safe by default and tests Host/Origin rejection plus bearer authentication.” | `support_desk/mcp_server.py`; `support_desk/store.py::create_mcp_proposal`; `mcp.example.json`; `docs/P3_MCP_REUSE_AUDIT.md` | `tests/test_mcp_server.py`; official Inspector 2.0.0 tool discovery, direct read, and proposal smoke recorded in `docs/mcp-server.md` | Static bearer auth is a tested resource-server seam, not live OAuth/JWT integration. SQLite is not distributed exactly-once. No MCP approval tool, App UI, resources, prompts, or multi-agent layer is claimed. |
| Workflow automation | “I built an approval-gated workflow that persists per-action attempts and receipts, retries only incomplete actions after partial failure, distinguishes retryable from terminal failures, and dead-letters exhausted runs.” | `support_desk/store.py` (`approve`, `action_receipts`, `action_attempts`, workflow events); `support_desk/tools.py` handlers | `tests/test_api.py::test_failed_adapter_can_retry_without_repeating_completed_actions`; `tests/test_api.py::test_retry_budget_moves_run_to_dead_letter`; `tests/test_agent_tools.py::test_approved_writes_are_idempotent_and_replayable` | Durability is SQLite and single-process. There is no distributed worker, lock/lease protocol, tenant boundary, or production throughput claim. |
| API / webhook integration | “I built a reusable REST/webhook action adapter with destination allowlisting, SSRF-oriented URL/DNS validation, bounded connect/read timeouts, secret references, configurable idempotency headers, recursive redaction, and explicit timeout/429/5xx/4xx/conflict/malformed-response handling.” | `support_desk/outbound.py`; `support_desk/fake_target.py`; `support_desk/tools.py::_send_notification`; `GET /api/adapters/outbound` | `tests/test_outbound_adapter.py`; `python -m support_desk.demo_agent` | This proves a generic client-owned HTTP contract against a local fake. It does not justify naming a CRM, messaging, email, calendar, helpdesk, n8n, or other SaaS integration. DNS is checked before connection; peer-address rebinding verification is not available. |
| Approval / reliability / audit | “I built a human approval boundary that shows raw tool arguments before writes, prevents handlers from running early, reuses idempotent action receipts, and persists planned calls, validation failures, approvals, attempts, results, retries and final states for replay.” | `support_desk/store.py` (`tool_calls`, workflow events, `approve`, `_execute_action`); `support_desk/schemas.py` (`Action`, `ToolCallRecord`) | `tests/test_agent_tools.py::test_read_runs_but_write_is_impossible_before_approval`; `tests/test_agent_tools.py::test_approved_writes_are_idempotent_and_replayable`; `tests/test_seeded_characterization.py` | This is application audit history, not a compliance certification, cryptographically immutable ledger, or exactly-once guarantee across distributed systems. |

## Short proposal variants

### AI agent/tool-calling job

> I recently built Relay’s bounded tool runtime: strict registered schemas,
> runtime argument and step limits, read/write risk classes, human approval
> before side effects, and replayable call events. Its deterministic no-key
> planner and optional OpenAI-compatible adapter use the same `ToolCall`
> contract, so the safety boundary does not depend on the model.

### MCP / agent integration job

> I recently exposed a governed workflow through the official MCP Python SDK
> v2 over both stdio and Streamable HTTP. Reads execute directly; write calls
> become typed, idempotent proposals and cannot run until Relay's separate human
> approval path. Tests cover structured schemas/results, malformed calls,
> cancellation, duplicates, failures, Host/Origin protection and bearer auth,
> and the official Inspector completes a credential-free subprocess flow.

### Workflow automation job

> I have a working approval-gated automation base that persists per-action
> attempts and idempotent receipts, retries only incomplete work after partial
> failure, and separates retryable failures from immediate or exhausted
> dead-letter outcomes. I would adapt the event, mapping and actions to your
> workflow rather than rebuild those reliability controls.

### API/webhook integration job

> I recently implemented a generic approved webhook action with an exact host
> allowlist, SSRF-oriented URL/DNS checks, bounded timeouts, secret references,
> configurable idempotency, redacted evidence and explicit handling for 409,
> 429, 5xx, 4xx, timeout and malformed responses. A credential-free local fake
> reproduces each path.

### Approval/reliability/audit job

> I built a workflow where the reviewer sees raw tool arguments before any
> write, completed actions are receipt-protected during retry, and persisted
> call plus event records reconstruct planning, validation, approval, attempts,
> results and final state.

## Reproduction

From a clean checkout with Python 3.11+:

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
python -m ruff check .
python -m pytest --cov=support_desk --cov-report=term-missing
python -m support_desk.demo_agent
npx -y @modelcontextprotocol/inspector@2.0.0 --cli --config mcp.example.json \
  --server relay --method tools/list --format json
```

Expected demo facts:

- provider is `deterministic` and `credentials_required` is `false`;
- `lookup_customer` is complete before approval;
- `apply_billing_hold`, `update_case` and `send_notification` are
  `awaiting_approval` before the decision;
- all four calls are complete after approval with one attempt each;
- the ticket moves from `needs_approval` to `resolved`;
- the local fake receives one request with a stable idempotency key;
- audit event types include planned calls, attempts, results, approval and the
  completed final state.

## Unsupported claims

Do not claim any of the following from this slice:

- a live or named CRM, messaging, email, calendar, helpdesk or automation
  platform integration;
- browser/desktop actions, multi-agent orchestration, MCP App UI or a chatbot UI;
- production deployment, measured throughput, high availability, tenant/RBAC
  isolation, compliance, or a client outcome metric;
- exactly-once delivery outside Relay's SQLite receipt boundary;
- credentialed model quality, accuracy or cost results;
- complete SSRF protection against DNS rebinding after the preflight check.
