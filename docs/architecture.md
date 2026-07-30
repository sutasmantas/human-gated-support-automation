# Architecture

```text
typed ticket
    │
    ▼
classification ──> policy retrieval ──> grounded draft
    │                                         │
    └────────── risk and routing rules ───────┘
                          │
                  human decision gate
                    │            │
                 reject       approve
                    │            │
                    ▼            ▼
                audit note   action executor
                                  │
                 ┌────────────────┼────────────────┐
                 ▼                ▼                ▼
            billing hold      CRM event      webhook/outbox
                 │                │                │
                 └──────── receipt + attempt ──────┘
                                  │
                          complete / retry /
                            dead-letter
```

## Server-side control boundary

The browser never performs operational side effects. Approval invokes one API
transition and the server executes each proposed action. A receipt is written
after a successful adapter call. Repeating approval or retrying a partial
failure checks those receipts first, so a completed billing hold or CRM event is
not repeated.

Rejection is also a state transition rather than a UI-only label. The operator
note is preserved in the same workflow-event stream used by the run inspector.

## Typed providers

- `local` uses transparent rules and templates for a reproducible no-key demo.
- `openai-compatible` requests structured classification and a
  policy-grounded draft from a configured chat-completions endpoint.

Both return the same typed workflow contract. Neither has access to the action
executor.

## Persistence and execution

SQLite stores tickets, sources, drafts, action state, attempts, receipts,
billing holds, CRM events, notification outbox entries and workflow events.
This makes the entire control path inspectable from the API and UI.

The notification adapter either:

- writes a local queued outbox receipt when no webhook is configured;
- records a delivered receipt after a successful webhook; or
- preserves the failure and attempt count for retry.

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
