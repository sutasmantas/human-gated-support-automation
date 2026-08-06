from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from support_desk.config import Settings
from support_desk.main import create_app
from support_desk.outbound import OutboundHTTPAdapter, OutboundResult, OutboundRetryableError


def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "runtime", automation_provider="local")


def renewal_ticket(client: TestClient) -> dict:
    return next(
        ticket
        for ticket in client.get("/api/tickets").json()
        if ticket["subject"] == "Renewal failed — service at risk"
    )


def test_seeded_ticket_is_triaged_and_grounded(tmp_path: Path) -> None:
    with TestClient(create_app(settings(tmp_path))) as client:
        response = client.get("/api/tickets")
        assert response.status_code == 200
        assert len(response.json()) == 4
        ticket = renewal_ticket(client)
        assert ticket["intent"] == "Failed renewal"
        assert ticket["priority"] == "Urgent"
        assert ticket["status"] == "needs_approval"
        assert len(ticket["sources"]) == 2
        assert {action["status"] for action in ticket["actions"]} == {"pending"}


def test_seeded_cases_have_domain_specific_intents_and_actions(tmp_path: Path) -> None:
    with TestClient(create_app(settings(tmp_path))) as client:
        tickets = {ticket["company"]: ticket for ticket in client.get("/api/tickets").json()}
        assert tickets["Northline Health"]["intent"] == "Invoice correction"
        assert tickets["Summit Bio"]["intent"] == "SSO configuration"
        assert tickets["Keystone Labs"]["intent"] == "Completed export"
        assert tickets["Keystone Labs"]["route"] == "Data Operations"
        assert [action["label"] for action in tickets["Keystone Labs"]["actions"]] == [
            "Close export delivery case",
            "Notify account team",
        ]


def test_approval_executes_actions_once_and_persists(tmp_path: Path) -> None:
    configured = settings(tmp_path)
    with TestClient(create_app(configured)) as client:
        ticket_id = renewal_ticket(client)["id"]
        approved = client.post(f"/api/tickets/{ticket_id}/approve")
        assert approved.status_code == 200
        payload = approved.json()
        assert payload["status"] == "resolved"
        assert {action["status"] for action in payload["actions"]} == {"completed"}

        repeated = client.post(f"/api/tickets/{ticket_id}/approve")
        assert repeated.status_code == 200
        assert repeated.json()["approved_at"] == payload["approved_at"]

    with TestClient(create_app(configured)) as client:
        ticket = renewal_ticket(client)
        assert ticket["status"] == "resolved"


def test_new_ticket_uses_risk_gate(tmp_path: Path) -> None:
    with TestClient(create_app(settings(tmp_path))) as client:
        created = client.post(
            "/api/tickets",
            json={
                "subject": "SSO metadata question",
                "body": "Please help us validate the SAML metadata URL for our new workspace.",
                "customer_name": "Sam Bell",
                "company": "Northstar",
                "arr_usd": 5_000,
                "active_users": 12,
            },
        )
        assert created.status_code == 201
        payload = created.json()
        assert payload["intent"] == "SSO configuration"
        assert payload["priority"] == "Normal"
        assert payload["status"] == "draft_ready"
        assert [source["title"] for source in payload["sources"]] == ["Identity support guide"]


def test_boolean_values_are_rejected_for_integer_ticket_fields(tmp_path: Path) -> None:
    payload = {
        "subject": "SSO metadata question",
        "body": "Please help us validate the SAML metadata URL for our new workspace.",
        "customer_name": "Sam Bell",
        "company": "Northstar",
        "arr_usd": 5_000,
        "active_users": 12,
    }
    with TestClient(create_app(settings(tmp_path))) as client:
        for field in ("arr_usd", "active_users"):
            invalid = {**payload, field: False}
            response = client.post("/api/tickets", json=invalid)
            assert response.status_code == 422
            assert response.json()["detail"][0]["loc"] == ["body", field]


def test_integer_valued_json_numbers_are_accepted(tmp_path: Path) -> None:
    payload = {
        "subject": "SSO metadata question",
        "body": "Please help us validate the SAML metadata URL for our new workspace.",
        "customer_name": "Sam Bell",
        "company": "Northstar",
        "arr_usd": 5_000.0,
        "active_users": 12.0,
    }
    with TestClient(create_app(settings(tmp_path))) as client:
        response = client.post("/api/tickets", json=payload)

    assert response.status_code == 201
    assert response.json()["arr_usd"] == 5_000
    assert response.json()["active_users"] == 12


def test_missing_ticket_returns_not_found(tmp_path: Path) -> None:
    with TestClient(create_app(settings(tmp_path))) as client:
        assert client.get("/api/tickets/missing").status_code == 404
        assert client.post("/api/tickets/missing/approve").status_code == 404


def test_rejection_is_audited_and_cannot_be_approved(tmp_path: Path) -> None:
    with TestClient(create_app(settings(tmp_path))) as client:
        ticket_id = renewal_ticket(client)["id"]
        rejected = client.post(
            f"/api/tickets/{ticket_id}/decision",
            json={"decision": "reject", "note": "Customer confirmation is still missing."},
        )
        assert rejected.status_code == 200
        assert rejected.json()["status"] == "rejected"
        assert client.post(f"/api/tickets/{ticket_id}/approve").status_code == 409
        events = client.get(f"/api/tickets/{ticket_id}/events").json()
        assert [
            event["event_type"]
            for event in events
            if event["event_type"] in {"ticket.created", "approval.rejected"}
        ] == [
            "ticket.created",
            "approval.rejected",
        ]


def test_failed_adapter_can_retry_without_repeating_completed_actions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    configured = Settings(
        data_dir=tmp_path / "runtime",
        automation_provider="local",
        notification_webhook_url="https://hooks.example.test/support",
        outbound_allowed_hosts="hooks.example.test",
    )
    calls = 0

    def flaky_send(self, payload, *, idempotency_key):
        del self, payload
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OutboundRetryableError("network_error", "temporary outage")
        return OutboundResult(
            status="delivered",
            classification="success",
            http_status=200,
            destination="https://hooks.example.test/support",
            idempotency_header="Idempotency-Key",
            idempotency_key=idempotency_key,
            request={},
            response={"status": "applied"},
        )

    monkeypatch.setattr(OutboundHTTPAdapter, "send", flaky_send)
    with TestClient(create_app(configured)) as client:
        ticket_id = renewal_ticket(client)["id"]
        first = client.post(f"/api/tickets/{ticket_id}/approve").json()
        assert first["status"] == "action_failed"
        assert [action["status"] for action in first["actions"]] == [
            "completed",
            "completed",
            "failed",
        ]

        retried = client.post(f"/api/tickets/{ticket_id}/retry").json()
        assert retried["status"] == "resolved"
        assert [action["attempts"] for action in retried["actions"]] == [1, 1, 2]
        events = client.get(f"/api/tickets/{ticket_id}/events").json()
        assert [
            event["event_type"]
            for event in events
            if event["event_type"].startswith("actions.")
        ][-2:] == [
            "actions.failed",
            "actions.completed",
        ]


def test_retry_budget_moves_run_to_dead_letter(tmp_path: Path, monkeypatch) -> None:
    configured = Settings(
        data_dir=tmp_path / "runtime",
        automation_provider="local",
        notification_webhook_url="https://hooks.example.test/support",
        outbound_allowed_hosts="hooks.example.test",
        max_action_attempts=2,
    )

    def unavailable(self, payload, *, idempotency_key):
        del self, payload, idempotency_key
        raise OutboundRetryableError("network_error", "provider unavailable")

    monkeypatch.setattr(OutboundHTTPAdapter, "send", unavailable)
    with TestClient(create_app(configured)) as client:
        ticket_id = renewal_ticket(client)["id"]
        assert client.post(f"/api/tickets/{ticket_id}/approve").json()["status"] == (
            "action_failed"
        )
        second = client.post(f"/api/tickets/{ticket_id}/retry")
        assert second.status_code == 200
        assert second.json()["status"] == "dead_letter"
        assert client.post(f"/api/tickets/{ticket_id}/retry").status_code == 409
