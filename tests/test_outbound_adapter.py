from __future__ import annotations

import json
import socket
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from support_desk.config import Settings
from support_desk.fake_target import create_fake_target
from support_desk.main import create_app
from support_desk.outbound import (
    REDACTED,
    OutboundHTTPAdapter,
    OutboundRetryableError,
    OutboundTerminalError,
)


def resolver_for(address: str):
    def resolve(*args: object, **kwargs: object) -> list[tuple]:
        del args, kwargs
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]

    return resolve


def settings(tmp_path: Path, scenario: str = "success", **overrides: object) -> Settings:
    return Settings(
        data_dir=tmp_path / "runtime",
        automation_provider="local",
        notification_webhook_url=f"https://fake.example.test/webhook/{scenario}",
        outbound_allowed_hosts="fake.example.test",
        **overrides,
    )


def bridge_transport(fake: TestClient) -> httpx.MockTransport:
    def bridge(request: httpx.Request) -> httpx.Response:
        response = fake.post(
            request.url.path,
            content=request.content,
            headers=dict(request.headers),
        )
        return httpx.Response(
            response.status_code,
            content=response.content,
            headers=dict(response.headers),
            request=request,
        )

    return httpx.MockTransport(bridge)


def test_success_uses_idempotency_secret_reference_and_redacts_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RELAY_FAKE_TOKEN", "never-return-this-secret")
    fake_app = create_fake_target()
    configured = settings(tmp_path, outbound_secret_ref="env:RELAY_FAKE_TOKEN")
    with TestClient(fake_app) as fake:
        adapter = OutboundHTTPAdapter(
            configured,
            transport=bridge_transport(fake),
            resolver=resolver_for("93.184.216.34"),
        )
        result = adapter.send(
            {
                "ticket_id": "CS-123",
                "customer_name": "Private Person",
                "nested": {"token": "request-secret", "safe": "visible"},
            },
            idempotency_key="CS-123:notify",
        )

    assert result.status == "delivered"
    assert result.classification == "success"
    assert result.idempotency_header == "Idempotency-Key"
    assert result.idempotency_key == "CS-123:notify"
    assert result.request["customer_name"] == REDACTED
    assert result.request["nested"] == {"token": REDACTED, "safe": "visible"}
    assert result.response["secret"] == REDACTED
    assert fake_app.state.received[0]["idempotency_key"] == "CS-123:notify"
    assert fake_app.state.received[0]["payload"]["customer_name"] == "Private Person"
    assert "never-return-this-secret" not in result.model_dump_json()


@pytest.mark.parametrize(
    "secret_ref",
    ("not-an-env-reference", "env:missing_lowercase", "env:MISSING_RELAY_TOKEN"),
)
def test_shared_secret_resolver_failure_is_terminal_and_does_not_send(
    tmp_path: Path,
    secret_ref: str,
) -> None:
    adapter = OutboundHTTPAdapter(
        settings(tmp_path, outbound_secret_ref=secret_ref),
        transport=httpx.MockTransport(lambda request: pytest.fail("request must not be sent")),
        resolver=resolver_for("93.184.216.34"),
    )

    with pytest.raises(OutboundTerminalError) as raised:
        adapter.send({"ticket_id": "CS-1"}, idempotency_key="safe-key")

    assert raised.value.classification == "secret_resolution_error"
    assert secret_ref not in str(raised.value)


@pytest.mark.parametrize(
    ("scenario", "expected_status", "expected_classification"),
    [
        ("success", "delivered", "success"),
        ("conflict", "already_applied", "conflict_already_applied"),
    ],
)
def test_local_fake_success_and_conflict_are_successful_outcomes(
    tmp_path: Path,
    scenario: str,
    expected_status: str,
    expected_classification: str,
) -> None:
    fake_app = create_fake_target()
    with TestClient(fake_app) as fake:
        result = OutboundHTTPAdapter(
            settings(tmp_path, scenario),
            transport=bridge_transport(fake),
            resolver=resolver_for("93.184.216.34"),
        ).send({"ticket_id": "CS-1"}, idempotency_key=f"key-{scenario}")

    assert result.status == expected_status
    assert result.classification == expected_classification


@pytest.mark.parametrize(
    ("scenario", "exception", "classification"),
    [
        ("rate-limit", OutboundRetryableError, "rate_limit"),
        ("terminal", OutboundTerminalError, "client_error"),
        ("invalid", OutboundTerminalError, "malformed_response"),
    ],
)
def test_local_fake_classifies_rate_limit_terminal_and_invalid_response(
    tmp_path: Path,
    scenario: str,
    exception: type[Exception],
    classification: str,
) -> None:
    fake_app = create_fake_target()
    with TestClient(fake_app) as fake:
        adapter = OutboundHTTPAdapter(
            settings(tmp_path, scenario),
            transport=bridge_transport(fake),
            resolver=resolver_for("93.184.216.34"),
        )
        with pytest.raises(exception, match=classification):
            adapter.send({"ticket_id": "CS-1"}, idempotency_key=f"key-{scenario}")


def test_timeout_and_server_failure_are_retryable(tmp_path: Path) -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    timeout_adapter = OutboundHTTPAdapter(
        settings(
            tmp_path,
            "timeout",
            outbound_connect_timeout_seconds=0.05,
            outbound_read_timeout_seconds=0.05,
        ),
        transport=httpx.MockTransport(timeout),
        resolver=resolver_for("93.184.216.34"),
    )
    with pytest.raises(OutboundRetryableError, match="timeout"):
        timeout_adapter.send({"ticket_id": "CS-1"}, idempotency_key="timeout-key")

    server_adapter = OutboundHTTPAdapter(
        settings(tmp_path / "server"),
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request)),
        resolver=resolver_for("93.184.216.34"),
    )
    with pytest.raises(OutboundRetryableError, match="server_error"):
        server_adapter.send({"ticket_id": "CS-1"}, idempotency_key="server-key")


def test_local_fake_timeout_scenario_is_real_and_credential_free() -> None:
    with TestClient(create_fake_target()) as fake:
        started = time.monotonic()
        response = fake.post(
            "/webhook/timeout",
            json={"ticket_id": "CS-1"},
            headers={"Idempotency-Key": "timeout-key"},
        )
        elapsed = time.monotonic() - started

    assert response.status_code == 200
    assert elapsed >= 0.20


@pytest.mark.parametrize(
    ("url", "allowed", "address", "allow_private", "classification"),
    [
        (
            "ftp://safe.example.test/hook",
            "safe.example.test",
            "93.184.216.34",
            False,
            "invalid_destination",
        ),
        (
            "https://user:pass@safe.example.test/hook",
            "safe.example.test",
            "93.184.216.34",
            False,
            "invalid_destination",
        ),
        (
            "https://other.example.test/hook",
            "safe.example.test",
            "93.184.216.34",
            False,
            "destination_not_allowlisted",
        ),
        (
            "http://safe.example.test/hook",
            "safe.example.test",
            "127.0.0.1",
            False,
            "unsafe_destination",
        ),
        (
            "http://safe.example.test/hook",
            "safe.example.test",
            "169.254.169.254",
            True,
            "unsafe_destination",
        ),
    ],
)
def test_destination_policy_rejects_unsafe_targets_before_sending(
    tmp_path: Path,
    url: str,
    allowed: str,
    address: str,
    allow_private: bool,
    classification: str,
) -> None:
    configured = Settings(
        data_dir=tmp_path / "runtime",
        notification_webhook_url=url,
        outbound_allowed_hosts=allowed,
        outbound_allow_private_networks=allow_private,
    )
    adapter = OutboundHTTPAdapter(
        configured,
        transport=httpx.MockTransport(lambda request: pytest.fail("request must not be sent")),
        resolver=resolver_for(address),
    )

    with pytest.raises(OutboundTerminalError, match=classification):
        adapter.send({"ticket_id": "CS-1"}, idempotency_key="safe-key")


def test_adapter_is_wired_to_approved_tool_and_persists_only_redacted_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RELAY_FAKE_TOKEN", "never-persist-this-secret")
    fake_app = create_fake_target()
    configured = settings(tmp_path, outbound_secret_ref="env:RELAY_FAKE_TOKEN")
    with TestClient(fake_app) as fake:
        adapter = OutboundHTTPAdapter(
            configured,
            transport=bridge_transport(fake),
            resolver=resolver_for("93.184.216.34"),
        )
        real_send = adapter.send

        def send_through_fake(self, payload, *, idempotency_key):
            del self
            return real_send(payload, idempotency_key=idempotency_key)

        monkeypatch.setattr(OutboundHTTPAdapter, "send", send_through_fake)
        with TestClient(create_app(configured)) as client:
            renewal = next(
                item
                for item in client.get("/api/tickets").json()
                if item["company"] == "Acme Logistics"
            )
            approved = client.post(f"/api/tickets/{renewal['id']}/approve")
            assert approved.status_code == 200
            assert approved.json()["status"] == "resolved"

            calls = client.get(f"/api/tickets/{renewal['id']}/tool-calls").json()
            notification = calls[-1]
            assert notification["result"]["adapter"]["request"]["customer_name"] == REDACTED
            assert notification["result"]["adapter"]["response"]["secret"] == REDACTED

            outbox = client.app.state.store.connection.execute(
                "SELECT payload_json FROM notification_outbox WHERE ticket_id = ?",
                (renewal["id"],),
            ).fetchone()[0]
            events = client.get(f"/api/tickets/{renewal['id']}/events").text
            description = client.get("/api/adapters/outbound").json()

    assert json.loads(outbox)["request"]["customer_name"] == REDACTED
    assert description["secret_ref"] == "env:RELAY_FAKE_TOKEN"
    assert "never-persist-this-secret" not in outbox
    assert "never-persist-this-secret" not in events
    assert fake_app.state.received[-1]["idempotency_key"].endswith(
        ":step-04-send-notification"
    )
