from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from support_desk.config import Settings
from support_desk.main import create_app


def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "runtime", automation_provider="local")


def test_seeded_ticket_is_triaged_and_grounded(tmp_path: Path) -> None:
    with TestClient(create_app(settings(tmp_path))) as client:
        response = client.get("/api/tickets")
        assert response.status_code == 200
        [ticket] = response.json()
        assert ticket["intent"] == "Failed renewal"
        assert ticket["priority"] == "Urgent"
        assert ticket["status"] == "needs_approval"
        assert len(ticket["sources"]) == 2
        assert {action["status"] for action in ticket["actions"]} == {"pending"}


def test_approval_executes_actions_once_and_persists(tmp_path: Path) -> None:
    configured = settings(tmp_path)
    with TestClient(create_app(configured)) as client:
        ticket_id = client.get("/api/tickets").json()[0]["id"]
        approved = client.post(f"/api/tickets/{ticket_id}/approve")
        assert approved.status_code == 200
        payload = approved.json()
        assert payload["status"] == "resolved"
        assert {action["status"] for action in payload["actions"]} == {"completed"}

        repeated = client.post(f"/api/tickets/{ticket_id}/approve")
        assert repeated.status_code == 200
        assert repeated.json()["approved_at"] == payload["approved_at"]

    with TestClient(create_app(configured)) as client:
        [ticket] = client.get("/api/tickets").json()
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


def test_missing_ticket_returns_not_found(tmp_path: Path) -> None:
    with TestClient(create_app(settings(tmp_path))) as client:
        assert client.get("/api/tickets/missing").status_code == 404
        assert client.post("/api/tickets/missing/approve").status_code == 404
