# Architecture

```text
Ticket intake
    │
    ▼
structured classification ──> policy selection ──> grounded draft
    │                                                │
    └──────────── risk rules ────────────────────────┘
                             │
                    human approval gate
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
        billing hold     CRM case event   webhook outbox
```

## Why the approval gate is server-side

The browser never executes operational actions. Approval calls one idempotent
API transition; the server records each adapter result and resolves the ticket
only after the actions are processed. Refreshing the browser or repeating the
request cannot create a second hold.

## Providers

- `local` uses transparent rules and templates for a no-key reproducible run.
- `openai-compatible` requests structured classification and a policy-grounded
  draft from a configured chat-completions endpoint.

Both providers produce the same typed workflow contract. Neither provider can
apply account changes without approval.

## Persistence

SQLite stores tickets, policy sources, drafts, action states, billing holds, CRM
events, and notification outbox records. External notifications use an optional
webhook; delivery failures remain visible in the outbox.

## Production additions

- authentication, tenant and role authorization
- provider-specific OAuth and secret storage
- retry/dead-letter processing for webhooks
- durable worker queue and concurrency controls
- customer data retention and deletion policies
- observability, rate limits, and content-safety policy
