from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse

from support_desk.config import PROJECT_ROOT, Settings
from support_desk.engine import LocalAutomation, create_automation
from support_desk.schemas import Stats, Ticket, TicketCreate, WorkflowStep
from support_desk.store import TicketStore

SAMPLE_TICKET = TicketCreate(
    subject="Renewal failed — service at risk",
    body=(
        "Our annual renewal failed this morning and the admin console says our workspace may "
        "be suspended in 48 hours. We have 120 people using the service and cannot lose access "
        "during month end. Can you confirm service will remain active while finance updates "
        "the payment method?"
    ),
    customer_name="Olivia Park",
    company="Acme Logistics",
    arr_usd=48_000,
    active_users=120,
)

WORKFLOW = [
    WorkflowStep(
        id="intake", name="New support ticket", kind="trigger", description="REST webhook"
    ),
    WorkflowStep(
        id="classify",
        name="Classify & prioritize",
        kind="automation",
        description="Structured triage",
    ),
    WorkflowStep(
        id="retrieve",
        name="Retrieve policies",
        kind="knowledge",
        description="Approved support policies",
    ),
    WorkflowStep(
        id="draft",
        name="Draft response",
        kind="automation",
        description="Policy-grounded draft",
    ),
    WorkflowStep(
        id="approval",
        name="Human approval",
        kind="gate",
        description="Required for risky actions",
    ),
    WorkflowStep(
        id="actions",
        name="Execute adapters",
        kind="action",
        description="Billing, CRM and notification outbox",
    ),
]


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        automation = create_automation(resolved)
        store = TicketStore(resolved)
        if not store.count():
            store.create(SAMPLE_TICKET, automation.process(SAMPLE_TICKET))
        application.state.automation = automation
        application.state.store = store
        yield
        store.close()

    app = FastAPI(title="AI Support Desk", version="0.1.0", lifespan=lifespan)

    def store(request: Request) -> TicketStore:
        return request.app.state.store

    def automation(request: Request) -> LocalAutomation:
        return request.app.state.automation

    @app.get("/api/health")
    def health(request: Request) -> dict[str, str]:
        return {"status": "ok", "automation_provider": automation(request).name}

    @app.get("/api/stats", response_model=Stats)
    def stats(request: Request) -> Stats:
        return store(request).stats(automation(request).name)

    @app.get("/api/tickets", response_model=list[Ticket])
    def tickets(request: Request) -> list[Ticket]:
        return store(request).list()

    @app.get("/api/tickets/{ticket_id}", response_model=Ticket)
    def ticket(ticket_id: str, request: Request) -> Ticket:
        try:
            return store(request).get(ticket_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Ticket not found.") from exc

    @app.post("/api/tickets", response_model=Ticket, status_code=status.HTTP_201_CREATED)
    def create_ticket(payload: TicketCreate, request: Request) -> Ticket:
        try:
            result = automation(request).process(payload)
        except (RuntimeError, KeyError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return store(request).create(payload, result)

    @app.post("/api/tickets/{ticket_id}/approve", response_model=Ticket)
    def approve(ticket_id: str, request: Request) -> Ticket:
        try:
            return store(request).approve(ticket_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Ticket not found.") from exc

    @app.get("/api/workflow", response_model=list[WorkflowStep])
    def workflow() -> list[WorkflowStep]:
        return WORKFLOW

    @app.get("/", include_in_schema=False)
    def frontend() -> FileResponse:
        return FileResponse(PROJECT_ROOT / "index.html")

    @app.get("/app.js", include_in_schema=False)
    def script() -> FileResponse:
        return FileResponse(PROJECT_ROOT / "app.js", media_type="text/javascript")

    @app.get("/styles.css", include_in_schema=False)
    def styles() -> FileResponse:
        return FileResponse(PROJECT_ROOT / "styles.css", media_type="text/css")

    return app


app = create_app()
