from __future__ import annotations

import asyncio
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import anyio
import httpx
import httpx2
import pytest
import uvicorn
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from pydantic import ValidationError

from support_desk.config import Settings
from support_desk.mcp_server import (
    RelayMCPRuntime,
    create_mcp_server,
    transport_security,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def settings_for(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "data_dir": tmp_path / "runtime",
        "deployment_mode": "test",
        "automation_provider": "local",
        "agent_provider": "deterministic",
    }
    values.update(overrides)
    return Settings(**values)


def renewal_request(key: str = "mcp-renewal-001", **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "idempotency_key": key,
        "subject": "Renewal failed for enterprise workspace",
        "body": "Our annual renewal failed and service may be suspended within 48 hours.",
        "customer_name": "Olivia Park",
        "company": "Acme Logistics",
        "arr_usd": 48_000,
        "active_users": 120,
    }
    values.update(overrides)
    return {"request": values}


@pytest.fixture
def mcp_runtime(tmp_path: Path) -> Iterator[tuple[object, RelayMCPRuntime]]:
    settings = settings_for(tmp_path)
    server, runtime = create_mcp_server(settings)
    try:
        yield server, runtime
    finally:
        runtime.close()


@pytest.mark.anyio
async def test_structured_catalog_reads_and_argument_validation(mcp_runtime) -> None:
    server, _runtime = mcp_runtime
    async with Client(server, raise_exceptions=True) as client:
        listed = await client.list_tools()
        names = [tool.name for tool in listed.tools]
        assert names == [
            "relay_list_governed_tools",
            "relay_list_runs",
            "relay_get_run",
            "relay_propose_support_run",
            "relay_wait_for_run",
        ]
        proposal_tool = next(
            tool for tool in listed.tools if tool.name == "relay_propose_support_run"
        )
        assert proposal_tool.input_schema["properties"]["request"]["$ref"].endswith(
            "MCPProposalInput"
        )
        assert proposal_tool.output_schema is not None

        catalog = await client.call_tool("relay_list_governed_tools", {})
        assert not catalog.is_error
        tools = catalog.structured_content["tools"]
        assert [item["name"] for item in tools] == [
            "lookup_customer",
            "apply_billing_hold",
            "update_case",
            "send_notification",
        ]
        assert tools[0]["risk_class"] == "read_only"
        assert all(item["risk_class"] != "read_only" for item in tools[1:])

        malformed = await client.call_tool("relay_list_runs", {"limit": 0})
        assert malformed.is_error
        extra = renewal_request()
        extra["request"]["unexpected"] = True
        invalid = await client.call_tool("relay_propose_support_run", extra)
        assert invalid.is_error


@pytest.mark.anyio
async def test_mcp_proposal_requires_existing_approval_and_is_idempotent(mcp_runtime) -> None:
    server, runtime = mcp_runtime
    async with Client(server, raise_exceptions=True) as client:
        first = await client.call_tool("relay_propose_support_run", renewal_request())
        assert not first.is_error
        proposed = first.structured_content
        assert proposed["approval_required"] is True
        assert proposed["external_writes_executed"] is False
        assert proposed["idempotency_reused"] is False
        ticket_id = proposed["ticket_id"]
        calls = proposed["proposed_calls"]
        assert calls[0]["tool_name"] == "lookup_customer"
        assert calls[0]["status"] == "completed"
        assert [item["status"] for item in calls[1:]] == [
            "awaiting_approval",
            "awaiting_approval",
            "awaiting_approval",
        ]

        for table in ("billing_holds", "case_events", "notification_outbox"):
            assert runtime.store.connection.execute(
                f"SELECT COUNT(*) FROM {table}"  # noqa: S608 - fixed test-only names
            ).fetchone()[0] == 0

        duplicate = await client.call_tool("relay_propose_support_run", renewal_request())
        assert duplicate.structured_content["ticket_id"] == ticket_id
        assert duplicate.structured_content["idempotency_reused"] is True
        assert runtime.store.count() == 1

        approved = runtime.store.approve(ticket_id)
        assert approved.status == "resolved"
        for table in ("billing_holds", "case_events", "notification_outbox"):
            assert runtime.store.connection.execute(
                f"SELECT COUNT(*) FROM {table}"  # noqa: S608 - fixed test-only names
            ).fetchone()[0] == 1

        after_approval = await client.call_tool(
            "relay_propose_support_run", renewal_request()
        )
        assert after_approval.structured_content["idempotency_reused"] is True
        assert after_approval.structured_content["external_writes_executed"] is True
        for table in ("billing_holds", "case_events", "notification_outbox"):
            assert runtime.store.connection.execute(
                f"SELECT COUNT(*) FROM {table}"  # noqa: S608 - fixed test-only names
            ).fetchone()[0] == 1

        conflict = await client.call_tool(
            "relay_propose_support_run",
            renewal_request(company="Different Company"),
        )
        assert conflict.is_error
        assert "different request" in conflict.content[0].text
        assert runtime.store.count() == 1


@pytest.mark.anyio
async def test_read_failure_and_wait_cancellation_have_no_side_effects(mcp_runtime) -> None:
    server, runtime = mcp_runtime
    async with Client(server, raise_exceptions=True) as client:
        missing = await client.call_tool("relay_get_run", {"ticket_id": "CS-MISSING"})
        assert missing.is_error
        assert "not found" in missing.content[0].text

        proposed = await client.call_tool("relay_propose_support_run", renewal_request())
        ticket_id = proposed.structured_content["ticket_id"]
        wait_task = asyncio.create_task(
            client.call_tool(
                "relay_wait_for_run",
                {
                    "ticket_id": ticket_id,
                    "timeout_seconds": 10,
                    "poll_interval_seconds": 0.05,
                },
            )
        )
        await anyio.sleep(0.15)
        wait_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await wait_task

        assert runtime.store.get(ticket_id).status == "needs_approval"
        assert runtime.store.connection.execute(
            "SELECT COUNT(*) FROM action_receipts"
        ).fetchone()[0] == 0


def test_network_exposure_and_auth_configuration_are_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="MCP_ALLOW_NETWORK"):
        settings_for(tmp_path, mcp_host="0.0.0.0")
    with pytest.raises(ValidationError, match="bearer authentication"):
        settings_for(tmp_path, mcp_host="0.0.0.0", mcp_allow_network=True)
    with pytest.raises(ValidationError, match="env:NAME"):
        settings_for(tmp_path, mcp_auth_mode="static-bearer", mcp_auth_token_ref="secret")


def _free_port() -> int:
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


@contextmanager
def running_http_server(server, settings: Settings) -> Iterator[str]:
    application = server.streamable_http_app(
        streamable_http_path=settings.mcp_http_path,
        stateless_http=True,
        json_response=True,
        max_request_body_size=settings.mcp_max_request_body_bytes,
        transport_security=transport_security(settings),
    )
    config = uvicorn.Config(
        application,
        host=settings.mcp_host,
        port=settings.mcp_port,
        log_level="error",
    )
    service = uvicorn.Server(config)
    thread = threading.Thread(target=service.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not service.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.02)
    if not service.started:
        service.should_exit = True
        thread.join(timeout=5)
        raise RuntimeError("MCP HTTP test server did not start.")
    try:
        yield f"http://127.0.0.1:{settings.mcp_port}{settings.mcp_http_path}"
    finally:
        service.should_exit = True
        thread.join(timeout=10)


@pytest.mark.anyio
async def test_streamable_http_host_origin_and_bearer_auth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = _free_port()
    monkeypatch.setenv("RELAY_MCP_TEST_TOKEN", "correct-test-token")
    settings = settings_for(
        tmp_path,
        mcp_port=port,
        mcp_auth_mode="static-bearer",
        mcp_auth_token_ref="env:RELAY_MCP_TEST_TOKEN",
        mcp_resource_server_url=f"http://127.0.0.1:{port}/mcp",
    )
    server, runtime = create_mcp_server(settings)
    try:
        with running_http_server(server, settings) as url:
            invalid_host = httpx.post(
                url,
                headers={
                    "Authorization": "Bearer correct-test-token",
                    "Host": "attacker.example",
                },
                json={},
                timeout=5,
            )
            assert invalid_host.status_code == 421

            invalid_origin = httpx.post(
                url,
                headers={
                    "Authorization": "Bearer correct-test-token",
                    "Origin": "https://attacker.example",
                },
                json={},
                timeout=5,
            )
            assert invalid_origin.status_code == 403

            missing_auth = httpx.post(url, json={}, timeout=5)
            assert missing_auth.status_code == 401
            assert "Bearer" in missing_auth.headers["WWW-Authenticate"]

            wrong_auth = httpx.post(
                url,
                headers={"Authorization": "Bearer wrong-test-token"},
                json={},
                timeout=5,
            )
            assert wrong_auth.status_code == 401

            async with httpx2.AsyncClient(
                headers={"Authorization": "Bearer correct-test-token"},
                timeout=httpx2.Timeout(10, read=30),
            ) as http_client:
                transport = streamable_http_client(url, http_client=http_client)
                async with Client(transport) as client:
                    listed = await client.list_tools()
                    assert "relay_propose_support_run" in [
                        tool.name for tool in listed.tools
                    ]
                    direct_read = await client.call_tool("relay_list_runs", {"limit": 5})
                    assert not direct_read.is_error
                    assert direct_read.structured_content == {"runs": []}
    finally:
        runtime.close()
