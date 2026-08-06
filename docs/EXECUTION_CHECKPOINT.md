# Relay execution checkpoint

## Shared OpenAPI consumer slice — 2026-08-06

- branch: `agent/toolbox-api-verification`
- isolated worktree: `portfolio_demos/worktrees/relay_api_toolbox`
- clean base: `9a4c45218fd3205f8169666ed019df828761f88e`
- reusable provider: AdapterProof
  `fa0296f4294b5149605c5fbf4e809adddba76e74`;
- correctness defect in scope: reject JSON booleans for the OpenAPI integer
  fields `arr_usd` and `active_users` instead of coercing them;
- security-specific work: postponed to the final toolbox backlog;
- license research: excluded by user direction.

Current gate: **LOCAL_CONSUMER_PASS_HOSTED_EXECUTION_PENDING**.

| Gate | Evidence | Status |
| --- | --- | --- |
| shared consumer contract | `adapterproof.openapi.json`; GET and POST `/api/tickets` | PASS |
| generated-case corrections | booleans rejected; schema-valid integral floats accepted; deterministic tests for both boundaries | PASS |
| real isolated execution | 77/77 generated cases; `NO_FINDINGS`; report SHA-256 `63aec0fe...990f9af` | PASS |
| committed receipt summary | `docs/evidence/adapterproof-openapi.json` | PASS |
| clean-environment project gate | Ruff; 41 passed; 85% coverage; JSON/YAML parse | PASS |
| reusable hosted workflow | exact provider commit configured, but neither side has executed this slice on GitHub | PENDING |

Exact next action: publish AdapterProof snapshot candidate
`fa0296f4294b5149605c5fbf4e809adddba76e74` before publishing this consumer
workflow, then preserve the hosted run URL. Local reuse and defect discovery are
proven; hosted reuse must not be claimed yet.

Last updated: 2026-08-03

This file is the authoritative Relay restart point. R0–R3 from
`RELAY_COVER_LETTER_EVIDENCE_HANDOFF.md` are complete and locally integrated.
The newer cross-portfolio depth plan now explicitly authorizes P3 MCP; that
authorization supersedes the historical R3 instruction to defer MCP. Visual
polish, named integrations, n8n expansion, and broad production hardening
remain out of scope.

P3 is complete and merged locally to Relay `main` at `a2a9b22`. The repository
was not pushed. Exact next cross-portfolio action: P4 PipelineForge in a new
repository/worktree.

## P3 MCP ledger

Only `PASS` authorizes the next row.

| P3 gate | Status | Evidence / next action |
| --- | --- | --- |
| Isolated baseline | PASS | `agent/relay-p3-mcp` in `portfolio_demos/worktrees/relay_p3_mcp`, based on clean integrated `main` `7d4711e` |
| GitHub/component comparison | PASS | `docs/P3_MCP_REUSE_AUDIT.md`; official SDK v2 adopted at tag `v2.0.0` / commit `6f69a37`; v1, third-party FastMCP, and custom JSON-RPC rejected |
| MCP tools and stdio | PASS | `96c671c`; five structured MCP tools; direct reads; idempotent proposal-only write path; no approval tool; `tests/test_mcp_server.py` |
| Streamable HTTP security/auth | PASS | real-socket tests cover loopback binding, invalid Host/Origin, missing/wrong bearer, and authenticated discovery/read; official SDK transport/auth reused |
| External Inspector and final gate | PASS | Inspector 2.0.0 stdio discovery/read/proposal and authenticated live-container HTTP discovery; Ruff clean; 39 tests, 85% coverage; fresh image built |

## Repository restart point

- Repository: `portfolio_demos/support_automation`
- Current P3 worktree: `portfolio_demos/worktrees/relay_p3_mcp`
- Current P3 branch: `agent/relay-p3-mcp`
- P3 base `main`: `7d4711ec991898bb6810e3db57c782e32a83f00e`
- Completed R0–R3 worktree: `portfolio_demos/worktrees/relay_cover_letter_core`
- Completed R0–R3 branch: `agent/relay-cover-letter-core`
- Original frozen base: `8cdf26c2831084e3dd59836db5bc1ef9e2f8bf73`
- Base `origin/main`: `8cdf26c2831084e3dd59836db5bc1ef9e2f8bf73`
- P3 base state: clean local `main` at `7d4711e`, five commits ahead of
  `origin/main`; remote was not changed.
- Current merged state: clean local `main` at `a2a9b22`, nine commits ahead of
  `origin/main`; remote remains unchanged.

Never switch branches in this worktree. Do not touch ContextSidecar or another
portfolio worktree from this branch.

## Phase ledger

Only `PASS` authorizes the next row.

| Slice | Status | Evidence |
| --- | --- | --- |
| R0 — freeze current truth | PASS | commit `a151293`; baseline lint/tests below; `tests/test_seeded_characterization.py`; current routes/schema/mechanisms/gaps recorded below |
| R1 — typed bounded tool executor | PASS | commit `56046ed`; `support_desk/tools.py`; persisted `tool_calls`; `/api/tools`; `/api/tickets/{id}/tool-calls`; `tests/test_agent_tools.py`; verification below |
| R2 — generic REST/webhook adapter | PASS | commit `7bf0656`; `support_desk/outbound.py`; `support_desk/fake_target.py`; `support_desk/demo_agent.py`; `tests/test_outbound_adapter.py`; verification below |
| R3 — proposal evidence and stopping gate | PASS | `docs/COVER_LETTER_EVIDENCE.md`; README no-key quickstart, approved-action example and extension seam; final verification below |

## R0 frozen current truth

### Existing routes

| Method | Route | Current behavior |
| --- | --- | --- |
| `GET` | `/api/health` | service and selected automation provider |
| `GET` | `/api/stats` | ticket/approval/resolution counts |
| `GET` | `/api/tickets` | persisted ticket, evidence, draft and action state |
| `GET` | `/api/tickets/{id}` | one persisted ticket |
| `POST` | `/api/tickets` | validate intake, classify, retrieve policy and draft |
| `POST` | `/api/tickets/{id}/approve` | persist approval and execute incomplete actions |
| `POST` | `/api/tickets/{id}/decision` | approve or reject with an operator note |
| `POST` | `/api/tickets/{id}/retry` | retry an `action_failed` run only |
| `GET` | `/api/tickets/{id}/events` | persisted workflow-event timeline |
| `GET` | `/api/workflow` | static workflow description |
| `GET` | `/`, `/app.js`, `/styles.css` | existing static UI assets |

### Existing persistence schema

SQLite owns the complete seeded flow in `TicketStore._initialize()`:

- `tickets`: intake, classification, evidence, draft, serialized actions,
  lifecycle state and approval time;
- `billing_holds`, `case_events`, `notification_outbox`: inspectable local
  side effects;
- `action_receipts`: `(ticket_id, action_id)` idempotency boundary;
- `action_attempts`: per-action attempt outcome and error;
- `workflow_events`: ordered audit timeline.

### Existing reliability and no-key behavior

- `local` deterministically classifies four seeded support cases without a key;
- the completed-export seed is automatically approved only when no notification
  webhook is configured, proving local actions and persisted receipts;
- urgent/high-ARR tickets remain `needs_approval` until the approval route runs;
- approval records `approval.approved` before side effects;
- successful actions receive durable receipts and are skipped during partial
  retry or repeated approval;
- HTTP failures preserve attempt/error state; retry exhaustion produces
  `dead_letter` and an audit event;
- rejection is persisted and blocks later approval;
- the optional notification webhook is the only current external write.

`tests/test_seeded_characterization.py` freezes the exact four-case no-key
behavior, policy evidence, action shapes, event ordering, automatic completed
seed, and restart persistence. Existing `tests/test_api.py` freezes approval,
rejection, idempotency, partial retry and dead-letter behavior.

### Hard-coded or not yet agent/tool capable

- Provider output is ticket triage/drafting, not a sequence of typed tool calls.
- Actions are a closed `billing_hold` / `case_update` / fallback-notification
  conditional embedded in `TicketStore`.
- Tool name, description, typed argument schema, risk class and handler are not
  registered data.
- Arguments have no independent runtime validation, size bound, or unknown-key
  rejection.
- There is no tool-step budget or bounded agent loop.
- Read-only versus externally visible/write tools are not modeled.
- Normal-priority tickets can be approved, but action risk does not itself
  enforce approval before the handler runs.
- The OpenAI-compatible provider returns classification JSON and cannot emit the
  same tool-call contract as a deterministic planner.
- Audit events summarize ticket/action outcomes but do not persist planned calls,
  validated arguments, each tool result, or a replayable call lifecycle.
- The notification webhook uses a direct `httpx.post` with one total timeout;
  it has no allowlist/SSRF validation, redaction, secret reference, configurable
  idempotency header, malformed-response check, or explicit retry taxonomy.
- `create_automation()` falls back to local for every non-OpenAI value; the
  settings literal prevents an invalid configured value, but there is no
  explicit production-mode ban on deterministic/fake providers.
- SQLite access is synchronous and process-local; concurrency/worker hardening
  remains outside this evidence slice.

## R0 verification

Environment setup required the declared dev extra:

```powershell
python -m pip install -e ".[dev]"
```

The first coverage invocation before that setup did not start because
`pytest-cov` was unavailable. After installing the repository-declared extras:

| Command | Result |
| --- | --- |
| `python -m ruff check .` | PASS — all checks passed |
| `python -m pytest --cov=support_desk --cov-report=term-missing` | PASS — 8 tests, 91% coverage at frozen base |

## R1 typed bounded tool executor

### Delivered behavior

- `ToolRegistry` exposes stable names, descriptions, strict Pydantic input
  schemas, `read_only` / `write` / `irreversible` risk, external-visibility
  metadata, and handlers.
- `ToolCall` is the shared output contract for deterministic and optional
  OpenAI-compatible function/tool-calling planners.
- `SUPPORT_MAX_TOOL_STEPS` bounds a plan before any handler runs;
  `SUPPORT_MAX_TOOL_ARGUMENT_BYTES`, strict schemas, and the registry reject
  oversized, extra, malformed, and unknown inputs.
- The deterministic no-key plan performs `lookup_customer`, then proposes the
  same support actions through `apply_billing_hold`, `update_case`, and
  `send_notification` tools.
- Read-only lookup runs during planning. Every write/irreversible call becomes
  an existing pending `Action` and can execute only after the existing approval
  route persists raw arguments and risk metadata.
- Existing `(ticket_id, action_id)` receipts, action attempts, partial retry,
  retry budget, dead-letter state, and workflow events remain the execution
  backbone. Tool handlers do not implement a parallel workflow engine.
- `tool_calls` persists sequence, arguments, risk, attempts, result/error and
  final status. `tool.planned`, `tool.validation_failed`, `tool.attempted`,
  `tool.result`, `approval.approved`, `agent.step_limit`, and `agent.completed`
  events make the lifecycle replayable.
- Retryable network/rate/server errors remain eligible for retry; terminal
  failures dead-letter immediately; already completed actions are not repeated.
- Production mode explicitly rejects the local automation and deterministic
  agent providers instead of silently selecting demo behavior.
- Existing ticket/action labels, no-key seed outcomes, approval, persistence,
  retry, rejection, and UI-facing response shapes remain compatible.

### R1 acceptance evidence

`tests/test_agent_tools.py` proves:

- valid read-only execution and an approved write lifecycle;
- no local or external write before approval;
- unknown tools, unknown keys and oversized arguments are rejected and audited;
- over-budget plans terminate before executing even the first read;
- repeated approval produces one billing hold, one case event and one outbox
  write;
- retryable and terminal failures produce distinct persisted states;
- existing partial success retries only the incomplete notification;
- the call table plus event stream reconstruct planned, approved, attempted,
  completed and failed states;
- repeated deterministic inputs produce identical calls and event ordering;
- the optional OpenAI-compatible adapter supplies the same `ToolCall` contract;
- demo providers are rejected explicitly in production mode.

| Command | Result |
| --- | --- |
| `python -m ruff check .` | PASS — all checks passed |
| `python -m pytest --cov=support_desk --cov-report=term-missing` | PASS — 20 tests, 90% coverage |

Known R1 boundary: notification HTTP still uses Relay's original direct call
with minimal retry classification. Destination security, bounded connect/read
timeouts, secrets, idempotency headers, redaction, complete response taxonomy,
and credential-free fake-target scenarios are R2.

## R2 generic REST/webhook adapter

### Delivered behavior

- `OutboundHTTPAdapter` is the single reusable HTTP action adapter used by the
  registered `send_notification` tool; it is not an unused helper or a catalog
  of named integrations.
- Destination policy requires an exact configured host allowlist, accepts only
  HTTP/HTTPS without embedded credentials, resolves the host before sending,
  blocks private/loopback/reserved/multicast/unspecified addresses by default,
  always blocks link-local/cloud-metadata targets, disables environment proxy
  inheritance, and refuses redirects.
- A deliberate `SUPPORT_OUTBOUND_ALLOW_PRIVATE_NETWORKS=true` escape hatch is
  required for the credential-free loopback fake. Metadata/link-local targets
  remain blocked even with that opt-in.
- Separate connect and read timeouts are bounded by validated settings.
- Secrets are configured only as `env:NAME` references. The adapter description,
  tool result, audit events and outbox never return the resolved value.
- The idempotency header name is configurable and the stable key combines the
  ticket and tool-call IDs; the fake confirms receipt of that exact key.
- Configured request/response fields are recursively redacted before tool-call,
  event or outbox evidence is persisted. The target still receives the real
  operational request.
- Success and HTTP 409/already-applied are completed outcomes. Timeout, network,
  HTTP 429 and 5xx are retryable. Other 4xx, redirects and malformed/non-object
  JSON are terminal.
- `support_desk.fake_target` provides credential-free success, conflict,
  delayed timeout, rate-limit, terminal and invalid-response routes.
- `python -m support_desk.demo_agent` starts that fake on loopback, creates a
  deterministic agent run, proves all write tools are blocked before approval,
  approves them, performs one real local HTTP action with an idempotency key,
  and prints the persisted lifecycle as JSON.

### R2 acceptance evidence

`tests/test_outbound_adapter.py` exercises the local fake through the adapter,
plus injected timeout/5xx transports and adversarial destination resolutions.
It proves nested request/response redaction, secret-reference resolution without
secret disclosure, configurable idempotency propagation, conflict semantics,
all required retry classes, and approved-tool integration through persisted
redacted evidence.

| Command | Result |
| --- | --- |
| `python -m ruff check .` | PASS — all checks passed |
| `python -m pytest --cov=support_desk --cov-report=term-missing` | PASS — 34 tests, 85% coverage; the separately executed demo CLI is included as 0% in this unit-test report |
| `python -m support_desk.demo_agent` | PASS — `needs_approval` to `resolved`; four completed tools; one fake-target write; external classification `success` |

Known R2 boundary: SSRF protection verifies configured host and preflight DNS
results, but `httpx` does not expose the connected peer address through this
adapter, so DNS rebinding cannot be rechecked after connection. The private-
network opt-in is intentionally operator-controlled and should be disabled for
internet deployments.

## R3 proposal evidence and stopping gate

### Delivered documentation

- `docs/COVER_LETTER_EVIDENCE.md` maps four permitted claim families to exact
  implementation files, focused tests and the no-key demo command: agent/tool
  calling, workflow automation, generic API/webhook integration, and
  approval/reliability/audit.
- Every claim has a concise proposal variant and an adjacent honest boundary.
  The ledger explicitly forbids named SaaS/MCP/n8n, production-scale,
  distributed exactly-once, credentialed model-quality and client-outcome
  claims.
- The README now exposes the two-command no-key quickstart, the complete
  tool-call-to-approved-action behavior, the stable tool/adapter extension
  seams, exact verification/demo commands, new API evidence routes and the
  production boundary.
- `docs/architecture.md` now reflects the actual bounded plan, read/write split,
  approval gate, generic outbound adapter and retry taxonomy.
- No frontend, screenshot, video, animation, hosting, named integration, MCP,
  n8n, multi-agent or cosmetic work was added.

### Final verification

| Command | Result |
| --- | --- |
| `python -m ruff check .` | PASS — all checks passed |
| `python -m pytest --cov=support_desk --cov-report=term-missing` | PASS — 34 tests, 85% aggregate coverage; demo CLI is executed separately and appears as 0% in this report |
| `python -m support_desk.demo_agent` | PASS — no credentials; lookup completed before approval; three writes awaited approval; ticket resolved; four tools completed once; fake received one HTTP action; audit sequence printed |
| `docker build -t relay-r3-gate:local .` | PASS — fresh Python 3.11 image built |
| `docker run --rm -d --name relay-r3-gate-run -p 127.0.0.1::8000 relay-r3-gate:local` plus live `GET /api/health` and `GET /api/tools` | PASS — health `ok`, provider `local`, four registered tools; temporary container stopped and removed |
| `git diff --check` | PASS |

UI/browser/accessibility/media verification is deliberately not applicable:
this slice made no frontend or visual changes and the handoff explicitly stops
before polish.

### Residual risks and honest boundary

- SQLite receipts and synchronous execution are a single-process public-demo
  boundary, not a distributed exactly-once or high-availability design.
- Authentication, tenant/RBAC isolation, durable workers, locks, production
  observability, managed secret storage and retention controls remain absent.
- SSRF policy performs strict preflight URL/host/address checks but cannot
  verify the connected peer address against DNS rebinding through current
  `httpx` transport metadata.
- The private-network opt-in is necessary for the local fake and should remain
  disabled for internet deployments; link-local/metadata/reserved/multicast/
  unspecified addresses stay blocked even when enabled.
- OpenAI-compatible tool calling is contract-tested with a local fixture, not a
  credentialed provider evaluation.
- The generic HTTP fake proves protocol behavior only. No named SaaS mapping,
  OAuth lifecycle, provider quota or production delivery is demonstrated.

## Historical R3 pause / handback

R0–R3 are complete and every required row is `PASS`. The minimum referenceable
evidence gate is met: realistic input reaches approved local and HTTP actions,
the same no-key contract exercises production seams, failure behavior is
focused-tested, the quickstart is runnable, claims are ledgered and boundaries
are explicit.

This was the correct stop under the 2026-08-01 handoff. The 2026-08-03 depth
plan later authorized the bounded P3 MCP slice recorded above. Visual polish,
R4/R5 productization, named adapters, n8n expansion, and multi-agent work remain
deferred.

## Integration record — R0–R3 to main

Date: 2026-08-01

- Exit gate: PASS; R0, R1, R2 and R3 were individually committed and every
  required ledger row above is `PASS`.
- Source branch: `agent/relay-cover-letter-core` at
  `dbf796b33cd055642885ffd441c38a9cd31c3922`.
- Main before integration: clean at
  `8cdf26c2831084e3dd59836db5bc1ef9e2f8bf73`, equal to fetched
  `origin/main`.
- Integration: strict fast-forward of the four commits; no merge rewrite,
  squash or conflict resolution.
- Verification on merged `main`:
  - `python -m ruff check .` — PASS;
  - `python -m pytest --cov=support_desk --cov-report=term-missing` — PASS,
    34 tests and 85% aggregate coverage;
  - `python -m support_desk.demo_agent` — PASS, no credentials, one local HTTP
    write, all four tools completed once after approval, final ticket state
    `resolved`.
- Remote state: intentionally not pushed; `origin/main` remains at `8cdf26c`
  until the user separately authorizes a push.
- Visual/UI/media verification: not applicable; no visual-polish files changed.
- Residual risks: unchanged from the R3 record above.
- Stop decision: Relay is closed at minimum referenceable evidence. Do not add
  polish or speculative named adapters. The next portfolio work should target a
  distinct uncovered deliverable rather than deepen Relay.

## P3 MCP closure

- Exit gate: `PASS`; isolated baseline, GitHub/component comparison, MCP
  tools/stdio, Streamable HTTP security/auth, official Inspector, tests, and
  deployable image all pass.
- P3 branch: `agent/relay-p3-mcp`, based on clean integrated Relay `main`
  `7d4711e`.
- Commits before this final checkpoint:
  - `8058e6c` — official SDK/Inspector comparison and pinned adopt/reject
    decisions;
  - `96c671c` — official-SDK MCP server, structured read/proposal tools,
    idempotent proposal mapping, fail-closed network/auth settings, and tests.
- Clean Linux verification: `ruff check .` passed;
  `pytest -o addopts='' -q --cov=support_desk --cov-report=term-missing`
  reported 39 passed and 85% aggregate coverage.
- In-memory/real-HTTP acceptance: structured schemas/results, malformed input,
  missing-run failure, direct reads, bounded cancellation, duplicate proposal
  reuse, changed-payload conflict, zero effects before approval, one effect per
  action after approval, non-loopback configuration rejection, Host 421,
  Origin 403, bearer 401, and an authenticated MCP discovery/read all pass.
- Inspector 2.0.0 stdio gate: discovered five tools, returned an empty direct
  read, and created one `needs_approval` proposal with one completed customer
  lookup plus three `awaiting_approval` writes. SQLite recorded one ticket and
  one proposal with zero receipts, billing holds, case events, or notifications.
- Deployment gate: fresh `relay-p3-mcp-gate:local` image built with `mcp==2.0.0`.
  Its normal Relay API returned health `ok` and four internal tools. A separate
  authenticated Streamable HTTP container returned 401 without a token and the
  official Inspector discovered all five MCP tools with the configured bearer.
- Defensible new claim: Relay is an official-SDK MCP server over stdio and
  Streamable HTTP whose structured read tools execute directly and whose
  idempotent support-run tool can only propose external writes behind Relay's
  existing human approval, receipt, retry, failure, and audit path.
- Limitations:
  - static bearer auth is a resource-server seam, not a live OAuth/JWT identity
    provider integration;
  - stdio trusts the local launching process;
  - proposal idempotency is single-process SQLite, not distributed exactly-once;
  - no MCP approval tool, App UI, resource, prompt, elicitation, sampling, or
    multi-agent layer exists;
  - existing Relay limits remain: no tenant boundary, durable worker,
    production observability, or peer-address DNS-rebinding verification.
- No frontend, screenshot, video, hosting, named SaaS adapter, n8n, or visual
  polish work was started.
- Merge result: `agent/relay-p3-mcp` at `b0f22bd` merged without conflicts to
  local Relay `main` at `a2a9b22`; not pushed.
- Exact next cross-portfolio action is P4 PipelineForge in a new
  repository/worktree. ContextSidecar remains complete elsewhere and outside
  this stream.
