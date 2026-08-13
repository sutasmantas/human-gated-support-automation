# Architecture

```text
typed ticket
    │
    ▼
classification ──> policy retrieval ──> grounded draft
                          │
                          ▼
                bounded tool-call plan
                  │                │
             read-only       write / irreversible
                  │                │
             execute now     human decision gate
                    │            │
                 reject       approve
                    │            │
                    ▼            ▼
                audit note   action executor
                                  │
                 ┌────────────────┼────────────────┐
                 ▼                ▼                ▼
            billing hold      case event     webhook/outbox
                 │                │                │
                 └──────── receipt + attempt ──────┘
                                  │
                          complete / retry /
                            dead-letter
```

MCP stdio / Streamable HTTP sits in front of the same boundary:

```text
MCP client -> structured read ---------------------------> Relay store
          \-> idempotent support-run proposal -> registry -> pending actions
                                                        -> human approval API
                                                        -> existing executor
```

The official SDK owns protocol negotiation, input/output schemas, cancellation,
stdio/HTTP framing, Host/Origin protection, and HTTP bearer enforcement. Relay
owns domain validation and action governance. No MCP call can invoke approval.

## Server-side control boundary

The browser never performs operational side effects. The registry validates
tool name, strict arguments, byte size, step count and risk. Read-only calls may
execute during planning; write and irreversible calls become pending actions.
Approval invokes one API transition and the server executes those actions. A
receipt is written after a successful handler call. Repeating approval or
retrying a partial failure checks those receipts first, so a completed billing
hold, case event or outbound request is not repeated.

Rejection is also a state transition rather than a UI-only label. The operator
note is preserved in the same workflow-event stream used by the run inspector.

## Typed providers

- `local` uses transparent rules and templates for a reproducible no-key demo.
- `openai-compatible` requests structured classification and a
  policy-grounded draft from a configured chat-completions endpoint.

The deterministic and OpenAI-compatible tool planners return the same bounded
`ToolCall` contract. Neither has direct access to a handler; the registry,
approval boundary and executor remain server-owned.

## Persistence and execution

SQLite stores tickets, sources, drafts, action state, attempts, receipts,
billing holds, CRM events, notification outbox entries and workflow events.
This makes the entire control path inspectable from the API and UI.

The generic outbound adapter either:

- writes a local queued outbox receipt when no webhook is configured;
- records a delivered or already-applied receipt after a successful/409 webhook;
- preserves the failure and attempt count for retry.

Before sending, it enforces the exact host allowlist, URL/DNS safety policy,
separate connect/read timeouts, idempotency header, secret-reference resolution
and configured request/response redaction. Timeout/network/429/5xx failures are
retryable; other 4xx, redirect and malformed-response failures are terminal.
Environment-secret syntax and lookup are owned by the pinned DeliveryGuard
provider. Relay translates provider resolution failures into its durable
configuration-error vocabulary; destination security and redaction remain
Relay-owned because DeliveryGuard does not implement those policies.

After `SUPPORT_MAX_ACTION_ATTEMPTS`, the case moves to dead-letter review.

## Deployment boundary

The repository deliberately keeps integration adapters small. Production
deployments still need:

- authentication, tenant and role authorization;
- provider-specific OAuth and managed secrets;
- a durable worker queue, locks and concurrency control;
- metrics, tracing, alerting and rate limits;
- customer-data retention and deletion controls;
- organization-specific content and approval policy.
