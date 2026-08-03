from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from support_desk.config import Settings
from support_desk.engine import AutomationResult, LocalAutomation
from support_desk.main import create_app
from support_desk.outbound import (
    OutboundHTTPAdapter,
    OutboundResult,
    OutboundRetryableError,
    OutboundTerminalError,
)
from support_desk.schemas import TicketCreate, ToolCall, ToolDescription
from support_desk.store import TicketStore
from support_desk.tools import OpenAICompatibleToolPlanner


class StaticPlanner:
    name = "test-static"

    def __init__(self, calls: list[ToolCall]) -> None:
        self.calls = calls

    def plan(
        self,
        ticket: TicketCreate,
        automation: AutomationResult,
        tools: list[ToolDescription],
    ) -> list[ToolCall]:
        del ticket, automation, tools
        return self.calls


def configured(tmp_path: Path, **overrides: object) -> Settings:
    return Settings(
        data_dir=tmp_path / "runtime",
        automation_provider="local",
        **overrides,
    )


def incoming_ticket() -> TicketCreate:
    return TicketCreate(
        subject="Renewal failed for test account",
        body="Our renewal failed and service is at risk while finance updates payment.",
        customer_name="Alex Example",
        company="Example Co",
        arr_usd=48_000,
        active_users=40,
    )


def create_with_planner(
    tmp_path: Path,
    planner: StaticPlanner,
    **setting_overrides: object,
) -> tuple[TicketStore, str]:
    settings = configured(tmp_path, **setting_overrides)
    store = TicketStore(settings, planner=planner)
    ticket = incoming_ticket()
    created = store.create(ticket, LocalAutomation(settings).process(ticket))
    return store, created.id


def renewal_ticket(client: TestClient) -> dict:
    return next(
        item
        for item in client.get("/api/tickets").json()
        if item["company"] == "Acme Logistics"
    )


def test_registered_catalogue_has_typed_risk_bounded_tools(tmp_path: Path) -> None:
    with TestClient(create_app(configured(tmp_path))) as client:
        catalogue = {item["name"]: item for item in client.get("/api/tools").json()}

    assert set(catalogue) == {
        "apply_billing_hold",
        "lookup_customer",
        "send_notification",
        "update_case",
    }
    assert catalogue["lookup_customer"]["risk_class"] == "read_only"
    assert catalogue["lookup_customer"]["externally_visible"] is False
    assert catalogue["send_notification"]["risk_class"] == "write"
    assert catalogue["send_notification"]["externally_visible"] is True
    assert catalogue["apply_billing_hold"]["risk_class"] == "irreversible"
    assert catalogue["update_case"]["input_schema"]["additionalProperties"] is False


def test_read_runs_but_write_is_impossible_before_approval(tmp_path: Path) -> None:
    with TestClient(create_app(configured(tmp_path))) as client:
        ticket = renewal_ticket(client)
        calls = client.get(f"/api/tickets/{ticket['id']}/tool-calls").json()
        connection = client.app.state.store.connection

        assert calls[0]["tool_name"] == "lookup_customer"
        assert calls[0]["status"] == "completed"
        assert calls[0]["result"]["company"] == "Acme Logistics"
        assert {call["status"] for call in calls[1:]} == {"awaiting_approval"}
        assert connection.execute(
            "SELECT COUNT(*) FROM billing_holds WHERE ticket_id = ?", (ticket["id"],)
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM case_events WHERE ticket_id = ?", (ticket["id"],)
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM notification_outbox WHERE ticket_id = ?", (ticket["id"],)
        ).fetchone()[0] == 0


def test_approved_writes_are_idempotent_and_replayable(tmp_path: Path) -> None:
    with TestClient(create_app(configured(tmp_path))) as client:
        ticket_id = renewal_ticket(client)["id"]
        assert client.post(f"/api/tickets/{ticket_id}/approve").json()["status"] == "resolved"
        assert client.post(f"/api/tickets/{ticket_id}/approve").json()["status"] == "resolved"

        connection = client.app.state.store.connection
        assert connection.execute(
            "SELECT COUNT(*) FROM billing_holds WHERE ticket_id = ?", (ticket_id,)
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM case_events WHERE ticket_id = ?", (ticket_id,)
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM notification_outbox WHERE ticket_id = ?", (ticket_id,)
        ).fetchone()[0] == 1

        calls = client.get(f"/api/tickets/{ticket_id}/tool-calls").json()
        assert [call["status"] for call in calls] == ["completed"] * 4
        assert [call["attempts"] for call in calls] == [1, 1, 1, 1]
        event_types = [
            item["event_type"]
            for item in client.get(f"/api/tickets/{ticket_id}/events").json()
        ]
        assert event_types.count("tool.planned") == 4
        assert event_types.count("tool.attempted") == 4
        assert event_types.count("tool.result") == 4
        assert event_types.index("approval.approved") < event_types.index(
            "tool.attempted", event_types.index("agent.completed") + 1
        )
        approval = next(
            item
            for item in client.get(f"/api/tickets/{ticket_id}/events").json()
            if item["event_type"] == "approval.approved"
        )
        approved_arguments = json.loads(approval["detail"])["calls"]
        assert approved_arguments[0]["arguments"] == {"days": 7}


@pytest.mark.parametrize(
    ("call", "expected_error"),
    [
        (
            ToolCall(id="bad-unknown", name="unknown_tool", arguments={}),
            "Unknown tool",
        ),
        (
            ToolCall(
                id="bad-arguments",
                name="lookup_customer",
                arguments={"company": "Example Co", "unexpected": True},
            ),
            "Extra inputs are not permitted",
        ),
    ],
)
def test_unknown_tool_and_unknown_arguments_are_audited(
    tmp_path: Path,
    call: ToolCall,
    expected_error: str,
) -> None:
    store, ticket_id = create_with_planner(tmp_path, StaticPlanner([call]))
    try:
        assert store.get(ticket_id).status == "dead_letter"
        record = store.tool_calls(ticket_id)[0]
        assert record.status == "validation_failed"
        assert expected_error in (record.error or "")
        assert [event.event_type for event in store.events(ticket_id)][-2:] == [
            "tool.validation_failed",
            "agent.completed",
        ]
    finally:
        store.close()


def test_oversized_arguments_are_rejected_before_handler(tmp_path: Path) -> None:
    call = ToolCall(
        id="bad-oversized",
        name="update_case",
        arguments={"event": "x" * 300},
    )
    store, ticket_id = create_with_planner(
        tmp_path,
        StaticPlanner([call]),
        max_tool_argument_bytes=256,
    )
    try:
        record = store.tool_calls(ticket_id)[0]
        assert record.status == "validation_failed"
        assert "exceed 256 bytes" in (record.error or "")
        assert store.connection.execute("SELECT COUNT(*) FROM case_events").fetchone()[0] == 0
    finally:
        store.close()


def test_step_limit_rejects_plan_without_execution(tmp_path: Path) -> None:
    calls = [
        ToolCall(
            id="step-01-lookup",
            name="lookup_customer",
            arguments={"company": "Example Co"},
        ),
        ToolCall(
            id="step-02-update",
            name="update_case",
            arguments={"event": "Update renewal case"},
        ),
    ]
    store, ticket_id = create_with_planner(
        tmp_path,
        StaticPlanner(calls),
        max_tool_steps=1,
    )
    try:
        assert store.get(ticket_id).status == "dead_letter"
        assert {item.status for item in store.tool_calls(ticket_id)} == {
            "step_limit_rejected"
        }
        assert "agent.step_limit" in [event.event_type for event in store.events(ticket_id)]
        assert store.connection.execute("SELECT COUNT(*) FROM case_events").fetchone()[0] == 0
    finally:
        store.close()


def test_retryable_and_terminal_failures_have_distinct_states(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = configured(
        tmp_path,
        notification_webhook_url="https://hooks.example.test/support",
        outbound_allowed_hosts="hooks.example.test",
    )
    responses: list[object] = [
        OutboundRetryableError("network_error", "temporary outage"),
        OutboundTerminalError("client_error", "Outbound target returned HTTP 400."),
    ]

    def fail_in_order(self, payload, *, idempotency_key) -> OutboundResult:
        del self, payload, idempotency_key
        outcome = responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, OutboundResult)
        return outcome

    monkeypatch.setattr(OutboundHTTPAdapter, "send", fail_in_order)
    with TestClient(create_app(settings)) as client:
        ticket_id = renewal_ticket(client)["id"]
        first = client.post(f"/api/tickets/{ticket_id}/approve").json()
        assert first["status"] == "action_failed"
        first_call = client.get(f"/api/tickets/{ticket_id}/tool-calls").json()[-1]
        assert first_call["status"] == "retryable_failed"

        second = client.post(f"/api/tickets/{ticket_id}/retry").json()
        assert second["status"] == "dead_letter"
        second_call = client.get(f"/api/tickets/{ticket_id}/tool-calls").json()[-1]
        assert second_call["status"] == "terminal_failed"
        assert second_call["attempts"] == 2


def test_deterministic_planner_repeats_calls_and_event_order(tmp_path: Path) -> None:
    payload = incoming_ticket().model_dump()
    with TestClient(create_app(configured(tmp_path))) as client:
        first = client.post("/api/tickets", json=payload).json()
        second = client.post("/api/tickets", json=payload).json()
        first_calls = client.get(f"/api/tickets/{first['id']}/tool-calls").json()
        second_calls = client.get(f"/api/tickets/{second['id']}/tool-calls").json()
        def comparable(calls: list[dict]) -> list[tuple]:
            return [
                (
                    item["id"],
                    item["tool_name"],
                    item["arguments"],
                    item["risk_class"],
                    item["status"],
                )
                for item in calls
            ]
        assert comparable(first_calls) == comparable(second_calls)

        first_events = client.get(f"/api/tickets/{first['id']}/events").json()
        second_events = client.get(f"/api/tickets/{second['id']}/events").json()
        assert [item["event_type"] for item in first_events] == [
            item["event_type"] for item in second_events
        ]


def test_openai_adapter_returns_the_same_tool_call_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = configured(
        tmp_path,
        agent_provider="openai-compatible",
        llm_base_url="https://llm.example.test/v1",
        llm_model="test-model",
    )
    captured: dict = {}

    def fake_post(*args: object, **kwargs: object) -> httpx.Response:
        del args
        captured.update(kwargs["json"])
        return httpx.Response(
            200,
            request=httpx.Request("POST", "https://llm.example.test/v1/chat/completions"),
            json={
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "provider-call-1",
                                    "function": {
                                        "name": "lookup_customer",
                                        "arguments": '{"company":"Example Co"}',
                                    },
                                }
                            ]
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    ticket = incoming_ticket()
    automation = LocalAutomation(settings).process(ticket)
    with TestClient(create_app(configured(tmp_path / "catalogue"))) as client:
        tools = [ToolDescription.model_validate(item) for item in client.get("/api/tools").json()]
    calls = OpenAICompatibleToolPlanner(settings).plan(ticket, automation, tools)

    assert calls == [
        ToolCall(
            id="provider-call-1",
            name="lookup_customer",
            arguments={"company": "Example Co"},
        )
    ]
    assert {item["function"]["name"] for item in captured["tools"]} == {
        "apply_billing_hold",
        "lookup_customer",
        "send_notification",
        "update_case",
    }


def test_demo_providers_are_rejected_explicitly_in_production(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="Production mode requires explicit non-demo"):
        configured(tmp_path, deployment_mode="production")
