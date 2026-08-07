from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from support_desk.config import Settings
from support_desk.engine import AutomationResult
from support_desk.schemas import Ticket, TicketCreate, ToolCall, ToolDescription

RiskClass = Literal["read_only", "write", "irreversible"]


class ToolValidationError(ValueError):
    pass


class ClassifiedToolError(RuntimeError):
    """A tool failure that carries the transport classification forward.

    The classification survives the hop from the outbound adapter to the
    durable effect gateway, so the persisted receipt records why an attempt
    failed rather than only that it failed.
    """

    def __init__(self, message: str, *, classification: str | None = None) -> None:
        self.classification = classification
        super().__init__(message)


class ToolRetryableError(ClassifiedToolError):
    pass


class ToolTerminalError(ClassifiedToolError):
    pass


class StrictToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LookupCustomerInput(StrictToolInput):
    company: str = Field(min_length=2, max_length=120)


class ApplyBillingHoldInput(StrictToolInput):
    days: int = Field(ge=1, le=14)


class UpdateCaseInput(StrictToolInput):
    event: str = Field(min_length=3, max_length=300)


class SendNotificationInput(StrictToolInput):
    route: str = Field(min_length=2, max_length=120)


@dataclass(frozen=True)
class ToolContext:
    connection: sqlite3.Connection
    settings: Settings
    ticket: Ticket
    now: str
    call_id: str


ToolHandler = Callable[[ToolContext, BaseModel], dict[str, Any]]


@dataclass(frozen=True)
class RegisteredTool:
    name: str
    description: str
    input_model: type[BaseModel]
    risk_class: RiskClass
    externally_visible: bool
    handler: ToolHandler
    label: str
    system: str

    def describe(self) -> ToolDescription:
        return ToolDescription(
            name=self.name,
            description=self.description,
            input_schema=self.input_model.model_json_schema(),
            risk_class=self.risk_class,
            externally_visible=self.externally_visible,
        )


class ToolRegistry:
    def __init__(self, tools: Sequence[RegisteredTool] = ()) -> None:
        self._tools: dict[str, RegisteredTool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: RegisteredTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> RegisteredTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolValidationError(f"Unknown tool: {name}") from exc

    def describe(self) -> list[ToolDescription]:
        return [tool.describe() for tool in self._tools.values()]

    def validate(
        self,
        call: ToolCall,
        *,
        max_argument_bytes: int,
    ) -> tuple[RegisteredTool, BaseModel]:
        raw = json.dumps(call.arguments, sort_keys=True, separators=(",", ":"))
        byte_count = len(raw.encode("utf-8"))
        if byte_count > max_argument_bytes:
            raise ToolValidationError(
                f"Tool arguments exceed {max_argument_bytes} bytes ({byte_count} received)."
            )
        tool = self.get(call.name)
        try:
            validated = tool.input_model.model_validate(call.arguments)
        except ValidationError as exc:
            raise ToolValidationError(str(exc)) from exc
        return tool, validated

    def execute(self, context: ToolContext, call: ToolCall) -> dict[str, Any]:
        tool, validated = self.validate(
            call,
            max_argument_bytes=context.settings.max_tool_argument_bytes,
        )
        return tool.handler(context, validated)


class ToolPlanner(Protocol):
    name: str

    def plan(
        self,
        ticket: TicketCreate,
        automation: AutomationResult,
        tools: Sequence[ToolDescription],
    ) -> list[ToolCall]: ...


class DeterministicToolPlanner:
    name = "deterministic"

    def plan(
        self,
        ticket: TicketCreate,
        automation: AutomationResult,
        tools: Sequence[ToolDescription],
    ) -> list[ToolCall]:
        del tools
        calls = [
            ToolCall(
                id="step-01-lookup-customer",
                name="lookup_customer",
                arguments={"company": ticket.company},
            )
        ]
        next_step = 2
        for action in automation.actions:
            if action.kind == "billing_hold":
                name = "apply_billing_hold"
                arguments: dict[str, Any] = {"days": 7}
            elif action.kind == "case_update":
                name = "update_case"
                arguments = {"event": action.label}
            else:
                name = "send_notification"
                arguments = {"route": automation.route}
            calls.append(
                ToolCall(
                    id=f"step-{next_step:02d}-{name.replace('_', '-')}",
                    name=name,
                    arguments=arguments,
                )
            )
            next_step += 1
        return calls


class OpenAICompatibleToolPlanner:
    name = "openai-compatible"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def plan(
        self,
        ticket: TicketCreate,
        automation: AutomationResult,
        tools: Sequence[ToolDescription],
    ) -> list[ToolCall]:
        if not self.settings.llm_base_url or not self.settings.llm_model:
            raise RuntimeError("OpenAI-compatible agent mode requires a base URL and model.")
        headers = {"Content-Type": "application/json"}
        if self.settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self.settings.llm_api_key}"
        response = httpx.post(
            f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
            headers=headers,
            timeout=45,
            json={
                "model": self.settings.llm_model,
                "temperature": 0,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Plan only the supplied tools. Read customer state first. "
                            "Never claim a write has already happened."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "ticket": ticket.model_dump(),
                                "intent": automation.intent,
                                "route": automation.route,
                                "proposed_actions": [
                                    action.model_dump() for action in automation.actions
                                ],
                            },
                            default=str,
                        ),
                    },
                ],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": tool.input_schema,
                        },
                    }
                    for tool in tools
                ],
                "tool_choice": "auto",
            },
        )
        response.raise_for_status()
        message = response.json()["choices"][0]["message"]
        calls = []
        for index, item in enumerate(message.get("tool_calls", []), start=1):
            function = item["function"]
            calls.append(
                ToolCall(
                    id=str(item.get("id") or f"step-{index:02d}-{function['name']}"),
                    name=str(function["name"]),
                    arguments=json.loads(function["arguments"]),
                )
            )
        return calls


def create_planner(settings: Settings) -> ToolPlanner:
    if settings.agent_provider == "openai-compatible":
        return OpenAICompatibleToolPlanner(settings)
    return DeterministicToolPlanner()


def _lookup_customer(context: ToolContext, payload: BaseModel) -> dict[str, Any]:
    arguments = LookupCustomerInput.model_validate(payload)
    if arguments.company.casefold() != context.ticket.company.casefold():
        raise ToolTerminalError("Customer lookup is restricted to the current ticket company.")
    return {
        "company": context.ticket.company,
        "arr_usd": context.ticket.arr_usd,
        "active_users": context.ticket.active_users,
        "status": context.ticket.status,
    }


def _apply_billing_hold(context: ToolContext, payload: BaseModel) -> dict[str, Any]:
    arguments = ApplyBillingHoldInput.model_validate(payload)
    context.connection.execute(
        "INSERT OR REPLACE INTO billing_holds VALUES (?, ?, ?, ?)",
        (context.ticket.id, context.ticket.company, arguments.days, context.now),
    )
    return {"message": f"{arguments.days}-day hold recorded", "days": arguments.days}


def _update_case(context: ToolContext, payload: BaseModel) -> dict[str, Any]:
    arguments = UpdateCaseInput.model_validate(payload)
    context.connection.execute(
        "INSERT INTO case_events (ticket_id, event, created_at) VALUES (?, ?, ?)",
        (context.ticket.id, f"{arguments.event} completed after approval", context.now),
    )
    return {"message": "Case event recorded", "event": arguments.event}


def _send_notification(context: ToolContext, payload: BaseModel) -> dict[str, Any]:
    arguments = SendNotificationInput.model_validate(payload)
    outbound = {
        "ticket_id": context.ticket.id,
        "company": context.ticket.company,
        "customer_name": context.ticket.customer_name,
        "route": arguments.route,
    }
    delivery_status = "queued"
    persisted_payload: dict[str, Any] = outbound
    adapter_evidence: dict[str, Any] | None = None
    if context.settings.notification_webhook_url:
        from support_desk.outbound import (
            OutboundHTTPAdapter,
            OutboundRetryableError,
            OutboundTerminalError,
        )

        try:
            adapter_result = OutboundHTTPAdapter(context.settings).send(
                outbound,
                idempotency_key=f"{context.ticket.id}:{context.call_id}",
            )
        except OutboundRetryableError as exc:
            raise ToolRetryableError(str(exc), classification=exc.classification) from exc
        except OutboundTerminalError as exc:
            raise ToolTerminalError(str(exc), classification=exc.classification) from exc
        delivery_status = adapter_result.status
        adapter_evidence = adapter_result.model_dump()
        persisted_payload = {
            "request": adapter_result.request,
            "response": adapter_result.response,
            "destination": adapter_result.destination,
            "idempotency_header": adapter_result.idempotency_header,
            "idempotency_key": adapter_result.idempotency_key,
        }
    context.connection.execute(
        """
        INSERT INTO notification_outbox
        (ticket_id, payload_json, delivery_status, created_at) VALUES (?, ?, ?, ?)
        """,
        (context.ticket.id, json.dumps(persisted_payload), delivery_status, context.now),
    )
    return {
        "message": f"Notification {delivery_status}",
        "delivery_status": delivery_status,
        "adapter": adapter_evidence,
    }


def create_default_registry() -> ToolRegistry:
    return ToolRegistry(
        [
            RegisteredTool(
                name="lookup_customer",
                description="Read the current ticket's customer and account context.",
                input_model=LookupCustomerInput,
                risk_class="read_only",
                externally_visible=False,
                handler=_lookup_customer,
                label="Look up customer record",
                system="Local customer records",
            ),
            RegisteredTool(
                name="apply_billing_hold",
                description="Apply a bounded service hold to the current customer account.",
                input_model=ApplyBillingHoldInput,
                risk_class="irreversible",
                externally_visible=True,
                handler=_apply_billing_hold,
                label="Apply billing hold",
                system="Local billing adapter",
            ),
            RegisteredTool(
                name="update_case",
                description="Append an approved event to the current support case.",
                input_model=UpdateCaseInput,
                risk_class="write",
                externally_visible=True,
                handler=_update_case,
                label="Update support case",
                system="Local case adapter",
            ),
            RegisteredTool(
                name="send_notification",
                description="Send or queue an approved workflow notification.",
                input_model=SendNotificationInput,
                risk_class="write",
                externally_visible=True,
                handler=_send_notification,
                label="Send workflow notification",
                system="Outbox webhook adapter",
            ),
        ]
    )
