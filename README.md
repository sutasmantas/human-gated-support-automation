# Relay — AI support operations

[![CI](https://github.com/sutasmantas/human-gated-support-automation/actions/workflows/ci.yml/badge.svg)](https://github.com/sutasmantas/human-gated-support-automation/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![MIT license](https://img.shields.io/badge/license-MIT-14B8A6)](LICENSE)

**A working case-operations console for AI-assisted support: investigate the
request, ground the draft in approved policy, keep consequential changes behind
review, and preserve a receipt for every action.**

Relay is more than a static dashboard. Its queue, case workspace, workflow
canvas and run inspector all read the same FastAPI service and persistent
SQLite state. Approve, reject and retry controls execute real state
transitions; completed actions remain idempotent when another action is retried.

![Relay case workspace](docs/screenshots/relay-case-workspace.png)

## What you can try

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/sutasmantas/human-gated-support-automation?quickstart=1)
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/sutasmantas/human-gated-support-automation)

The no-key local provider seeds four fictional cases that exercise different
operating paths:

- a failed enterprise renewal that needs approval before billing and CRM changes;
- an SSO request that can be reviewed or rejected with an operator note;
- an invoice correction with retrieved policy evidence;
- a completed export that demonstrates action receipts and run history.

Open the renewal case, inspect its evidence and proposed side effects, then
approve it. The server records a billing hold, CRM event and notification
receipt. Repeating the approval cannot duplicate completed effects.

<details>
<summary>Workflow and run-inspector views</summary>

![Relay executable workflow](docs/screenshots/relay-workflow.png)

![Relay run inspector](docs/screenshots/relay-run-inspector.png)

</details>

## Control flow

1. `POST /api/tickets` accepts and validates a support request.
2. The configured provider returns typed intent, priority, sentiment, route,
   confidence, risk and a proposed reply.
3. Approved policy excerpts are attached as evidence.
4. Risk rules determine whether operational actions need human approval.
5. Approval executes local billing and CRM adapters plus an optional
   notification webhook.
6. Each action has its own durable attempt and receipt. A retry skips completed
   actions and moves an exhausted failure to dead-letter review.
7. Workflow events preserve the decision and execution timeline.

The browser and the included n8n template call the same API. Model output cannot
bypass the server-side approval boundary.

## Run locally

Requirements: Python 3.11+.

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
uvicorn support_desk.main:app --reload
```

Open <http://localhost:8000>. The OpenAPI reference is at
<http://localhost:8000/docs>.

State persists in `data/runtime/support.sqlite3`. Delete that development
database only when you intentionally want to restore the four seed cases.

## Use a model endpoint

Relay runs without credentials. To use an OpenAI-compatible structured-output
provider, copy `.env.example` to `.env` and configure:

```dotenv
SUPPORT_AUTOMATION_PROVIDER=openai-compatible
SUPPORT_LLM_BASE_URL=https://your-provider.example/v1
SUPPORT_LLM_API_KEY=your-key
SUPPORT_LLM_MODEL=your-model
```

The model receives ticket and account context plus selected policy excerpts. It
can classify and draft; it cannot execute actions.

## Connect notifications

Set `SUPPORT_NOTIFICATION_WEBHOOK_URL` to deliver approved notifications. When
it is unset, Relay writes the notification to its local outbox. Failed calls
remain visible with their attempt count and may be retried up to
`SUPPORT_MAX_ACTION_ATTEMPTS`.

## Docker and n8n

```bash
docker compose up --build
```

Runtime state is persisted in the `support-data` volume.

An importable n8n workflow is included at
[`n8n/support-approval-workflow.json`](n8n/support-approval-workflow.json).

```bash
docker compose --profile n8n up --build
```

Open n8n at <http://localhost:5678> and import the JSON file from `/workflows`.
It is inactive by default.

## API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Provider and service health |
| `GET` | `/api/stats` | Queue and run counts |
| `GET` | `/api/tickets` | Cases with decisions, evidence and action state |
| `POST` | `/api/tickets` | Intake, classify, retrieve and draft |
| `POST` | `/api/tickets/{id}/approve` | Approve and execute pending actions |
| `POST` | `/api/tickets/{id}/decision` | Reject with an operator note |
| `POST` | `/api/tickets/{id}/retry` | Retry only incomplete actions |
| `GET` | `/api/tickets/{id}/events` | Retrieve the audit timeline |
| `GET` | `/api/workflow` | Machine-readable workflow definition |

## Verification

```bash
ruff check .
pytest --cov=support_desk --cov-report=term-missing
```

Tests cover classification, evidence, risk gating, approval, rejection,
per-action receipts, idempotency, partial failure, retry, dead-letter
exhaustion, persistence, intake and missing resources. GitHub Actions runs the
same checks on every push and pull request.

## Production boundary

The local adapters perform real, inspectable state changes, but this repository
does not claim live Stripe, Salesforce or Slack access. Provider OAuth,
authentication, tenant isolation, managed secrets, a durable worker queue,
production observability and retention controls remain deployment-specific.
See [docs/architecture.md](docs/architecture.md) for the boundary in detail.

## License

MIT
