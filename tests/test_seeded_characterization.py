from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from support_desk.config import Settings
from support_desk.main import create_app


def test_no_key_seeded_support_flow_is_frozen(tmp_path: Path) -> None:
    configured = Settings(data_dir=tmp_path / "runtime", automation_provider="local")

    with TestClient(create_app(configured)) as client:
        assert client.get("/api/health").json() == {
            "status": "ok",
            "automation_provider": "local",
        }
        tickets = {item["company"]: item for item in client.get("/api/tickets").json()}

        assert set(tickets) == {
            "Acme Logistics",
            "Keystone Labs",
            "Northline Health",
            "Summit Bio",
        }
        assert {
            company: (ticket["intent"], ticket["route"], ticket["status"])
            for company, ticket in tickets.items()
        } == {
            "Acme Logistics": ("Failed renewal", "Billing Ops", "needs_approval"),
            "Keystone Labs": ("Completed export", "Data Operations", "resolved"),
            "Northline Health": ("Invoice correction", "Billing Ops", "draft_ready"),
            "Summit Bio": ("SSO configuration", "Technical Support", "draft_ready"),
        }

        renewal = tickets["Acme Logistics"]
        assert [source["title"] for source in renewal["sources"]] == [
            "Enterprise billing policy",
            "Failed renewal playbook",
        ]
        assert [action["kind"] for action in renewal["actions"]] == [
            "billing_hold",
            "case_update",
            "notification",
        ]
        assert {action["status"] for action in renewal["actions"]} == {"pending"}
        assert [
            event["event_type"]
            for event in client.get(f"/api/tickets/{renewal['id']}/events").json()
            if event["event_type"] in {
                "ticket.created",
                "approval.approved",
                "actions.completed",
            }
        ] == ["ticket.created"]

        completed = tickets["Keystone Labs"]
        assert [action["kind"] for action in completed["actions"]] == [
            "case_update",
            "notification",
        ]
        assert {action["status"] for action in completed["actions"]} == {"completed"}
        assert [
            event["event_type"]
            for event in client.get(f"/api/tickets/{completed['id']}/events").json()
            if event["event_type"] in {
                "ticket.created",
                "approval.approved",
                "actions.completed",
            }
        ] == ["ticket.created", "approval.approved", "actions.completed"]

    with TestClient(create_app(configured)) as client:
        persisted = {item["company"]: item for item in client.get("/api/tickets").json()}
        assert len(persisted) == 4
        assert persisted["Keystone Labs"]["status"] == "resolved"
        assert persisted["Acme Logistics"]["status"] == "needs_approval"
