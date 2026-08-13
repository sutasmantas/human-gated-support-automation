from __future__ import annotations

import argparse
import secrets
from typing import Annotated, Literal

import anyio
from deliveryguard.secrets import EnvironmentSecretResolver, SecretResolutionError
from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

from support_desk.config import Settings
from support_desk.engine import LocalAutomation, create_automation
from support_desk.schemas import (
    Ticket,
    TicketCreate,
    ToolCallRecord,
    ToolDescription,
    WorkflowEvent,
)
from support_desk.store import TicketStore

TERMINAL_RUN_STATES = {"resolved", "rejected", "dead_letter"}


class MCPProposalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(
        min_length=8,
        max_length=120,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]+$",
        description="Stable caller key. Reuse only for the identical proposal.",
    )
    subject: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=10, max_length=5000)
    customer_name: str = Field(min_length=2, max_length=120)
    company: str = Field(min_length=2, max_length=120)
    arr_usd: int = Field(default=0, ge=0)
    active_users: int = Field(default=1, ge=1)

    def ticket(self) -> TicketCreate:
        return TicketCreate.model_validate(
            self.model_dump(exclude={"idempotency_key"})
        )


class MCPToolCatalog(BaseModel):
    tools: list[ToolDescription]
    execution_boundary: str


class MCPRunSummary(BaseModel):
    ticket_id: str
    subject: str
    company: str
    status: str
    proposed_actions: int


class MCPRunList(BaseModel):
    runs: list[MCPRunSummary]


class MCPRunSnapshot(BaseModel):
    ticket: Ticket
    tool_calls: list[ToolCallRecord]
    events: list[WorkflowEvent]


class MCPProposalResult(BaseModel):
    ticket_id: str
    status: str
    idempotency_key: str
    idempotency_reused: bool
    approval_required: bool
    external_writes_executed: bool
    approval_endpoint: str
    proposed_calls: list[ToolCallRecord]


class MCPWaitResult(BaseModel):
    ticket_id: str
    status: str
    terminal: bool
    timed_out: bool


class RelayMCPRuntime:
    def __init__(
        self,
        settings: Settings,
        *,
        store: TicketStore | None = None,
        automation: LocalAutomation | None = None,
    ) -> None:
        self.settings = settings
        self.store = store or TicketStore(settings)
        self.automation = automation or create_automation(settings)
        self._owns_store = store is None

    def close(self) -> None:
        if self._owns_store:
            self.store.close()

    def catalog(self) -> MCPToolCatalog:
        return MCPToolCatalog(
            tools=self.store.registry.describe(),
            execution_boundary=(
                "Read operations execute directly. Write and irreversible calls are persisted "
                "as proposals and execute only through Relay's human approval API."
            ),
        )

    def list_runs(self, limit: int) -> MCPRunList:
        return MCPRunList(
            runs=[
                MCPRunSummary(
                    ticket_id=ticket.id,
                    subject=ticket.subject,
                    company=ticket.company,
                    status=ticket.status,
                    proposed_actions=len(ticket.actions),
                )
                for ticket in self.store.list()[:limit]
            ]
        )

    def snapshot(self, ticket_id: str) -> MCPRunSnapshot:
        try:
            ticket = self.store.get(ticket_id)
        except KeyError as exc:
            raise ValueError("Relay run was not found.") from exc
        return MCPRunSnapshot(
            ticket=ticket,
            tool_calls=self.store.tool_calls(ticket_id),
            events=self.store.events(ticket_id),
        )

    def propose(self, request: MCPProposalInput) -> MCPProposalResult:
        incoming = request.ticket()
        automation = self.automation.process(incoming)
        ticket, reused = self.store.create_mcp_proposal(
            incoming,
            automation,
            request.idempotency_key,
        )
        calls = self.store.tool_calls(ticket.id)
        return MCPProposalResult(
            ticket_id=ticket.id,
            status=ticket.status,
            idempotency_key=request.idempotency_key,
            idempotency_reused=reused,
            approval_required=any(call.risk_class != "read_only" for call in calls),
            external_writes_executed=any(
                action.externally_visible and action.status == "completed"
                for action in ticket.actions
            ),
            approval_endpoint=f"/api/tickets/{ticket.id}/approve",
            proposed_calls=calls,
        )


class StaticBearerVerifier(TokenVerifier):
    def __init__(
        self,
        settings: Settings,
        resolver: EnvironmentSecretResolver | None = None,
    ) -> None:
        self.settings = settings
        self.resolver = resolver or EnvironmentSecretResolver()

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            expected = self.resolver.resolve(self.settings.mcp_auth_token_ref)
        except SecretResolutionError:
            return None
        if not secrets.compare_digest(token, expected):
            return None
        return AccessToken(
            token=token,
            client_id="relay-static-client",
            scopes=self.settings.required_mcp_scopes,
            subject="relay-operator",
        )


def create_mcp_server(
    settings: Settings,
    *,
    runtime: RelayMCPRuntime | None = None,
) -> tuple[MCPServer, RelayMCPRuntime]:
    resolved_runtime = runtime or RelayMCPRuntime(settings)
    authentication: dict[str, object] = {}
    if settings.mcp_auth_mode == "static-bearer":
        authentication = {
            "token_verifier": StaticBearerVerifier(settings),
            "auth": AuthSettings(
                issuer_url=AnyHttpUrl(settings.mcp_issuer_url),
                resource_server_url=AnyHttpUrl(settings.mcp_resource_server_url),
                required_scopes=settings.required_mcp_scopes,
            ),
        }
    server = MCPServer(
        "Relay governed operations",
        description=(
            "Inspect Relay runs and propose typed support actions. External writes always "
            "remain behind Relay's separate human approval boundary."
        ),
        version="2.1.0",
        **authentication,
    )

    @server.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )
    )
    def relay_list_governed_tools() -> MCPToolCatalog:
        """List Relay's internal typed tools, risk classes, and input schemas."""
        return resolved_runtime.catalog()

    @server.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )
    )
    def relay_list_runs(
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> MCPRunList:
        """List recent Relay runs without executing any action."""
        return resolved_runtime.list_runs(limit)

    @server.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )
    )
    def relay_get_run(ticket_id: str) -> MCPRunSnapshot:
        """Read one Relay run with its governed tool calls and audit timeline."""
        return resolved_runtime.snapshot(ticket_id)

    @server.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )
    )
    def relay_propose_support_run(request: MCPProposalInput) -> MCPProposalResult:
        """Plan a support run; persist external writes as unexecuted approval proposals."""
        return resolved_runtime.propose(request)

    @server.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )
    )
    async def relay_wait_for_run(
        ticket_id: str,
        timeout_seconds: Annotated[float, Field(gt=0, le=30)] = 5,
        poll_interval_seconds: Annotated[float, Field(ge=0.05, le=1)] = 0.2,
    ) -> MCPWaitResult:
        """Wait cancellably for a run to reach a terminal state or a bounded timeout."""
        deadline = anyio.current_time() + timeout_seconds
        while True:
            snapshot = resolved_runtime.snapshot(ticket_id)
            terminal = snapshot.ticket.status in TERMINAL_RUN_STATES
            if terminal:
                return MCPWaitResult(
                    ticket_id=ticket_id,
                    status=snapshot.ticket.status,
                    terminal=True,
                    timed_out=False,
                )
            if anyio.current_time() >= deadline:
                return MCPWaitResult(
                    ticket_id=ticket_id,
                    status=snapshot.ticket.status,
                    terminal=False,
                    timed_out=True,
                )
            await anyio.sleep(poll_interval_seconds)

    return server, resolved_runtime


def transport_security(settings: Settings) -> TransportSecuritySettings | None:
    if not settings.allowed_mcp_hosts and not settings.allowed_mcp_origins:
        return None
    return TransportSecuritySettings(
        allowed_hosts=settings.allowed_mcp_hosts,
        allowed_origins=settings.allowed_mcp_origins,
    )


def run(transport: Literal["stdio", "http"] = "stdio") -> None:
    settings = Settings()
    if transport == "http" and settings.deployment_mode == "production":
        if settings.mcp_auth_mode == "none":
            raise RuntimeError("Production Streamable HTTP requires MCP bearer authentication.")
    server, runtime = create_mcp_server(settings)
    try:
        if transport == "stdio":
            server.run("stdio")
        else:
            server.run(
                "streamable-http",
                host=settings.mcp_host,
                port=settings.mcp_port,
                streamable_http_path=settings.mcp_http_path,
                stateless_http=True,
                json_response=True,
                max_request_body_size=settings.mcp_max_request_body_bytes,
                transport_security=transport_security(settings),
            )
    finally:
        runtime.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Relay's governed MCP adapter.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default="stdio",
        help="stdio for local launchers; http for loopback Streamable HTTP.",
    )
    arguments = parser.parse_args()
    run(arguments.transport)


if __name__ == "__main__":
    main()
