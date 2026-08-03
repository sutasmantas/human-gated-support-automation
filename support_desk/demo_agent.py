from __future__ import annotations

import json
import socket
import tempfile
import threading
import time
from pathlib import Path

import httpx
import uvicorn
from fastapi.testclient import TestClient

from support_desk.config import Settings
from support_desk.fake_target import create_fake_target
from support_desk.main import create_app


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def run_demo() -> dict[str, object]:
    port = _available_port()
    fake_target = create_fake_target()
    server = uvicorn.Server(
        uvicorn.Config(fake_target, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    health_url = f"http://127.0.0.1:{port}/health"
    while time.monotonic() < deadline:
        try:
            if httpx.get(health_url, timeout=0.2).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.05)
    else:
        server.should_exit = True
        thread.join(timeout=2)
        raise RuntimeError("Local fake target did not start within five seconds.")

    try:
        with tempfile.TemporaryDirectory(prefix="relay-agent-demo-") as directory:
            settings = Settings(
                data_dir=Path(directory),
                automation_provider="local",
                agent_provider="deterministic",
                notification_webhook_url=(
                    f"http://127.0.0.1:{port}/webhook/success"
                ),
                outbound_allowed_hosts="127.0.0.1",
                outbound_allow_private_networks=True,
                outbound_connect_timeout_seconds=1,
                outbound_read_timeout_seconds=1,
            )
            with TestClient(create_app(settings)) as client:
                ticket = next(
                    item
                    for item in client.get("/api/tickets").json()
                    if item["company"] == "Acme Logistics"
                )
                before = client.get(f"/api/tickets/{ticket['id']}/tool-calls").json()
                approved = client.post(f"/api/tickets/{ticket['id']}/approve").json()
                after = client.get(f"/api/tickets/{ticket['id']}/tool-calls").json()
                events = client.get(f"/api/tickets/{ticket['id']}/events").json()
                output: dict[str, object] = {
                    "provider": "deterministic",
                    "credentials_required": False,
                    "ticket_status_before": ticket["status"],
                    "tool_states_before_approval": [
                        {"tool": item["tool_name"], "status": item["status"]}
                        for item in before
                    ],
                    "ticket_status_after": approved["status"],
                    "tool_states_after_approval": [
                        {
                            "tool": item["tool_name"],
                            "status": item["status"],
                            "attempts": item["attempts"],
                        }
                        for item in after
                    ],
                    "external_action": after[-1]["result"]["adapter"]["classification"],
                    "idempotency_key": after[-1]["result"]["adapter"]["idempotency_key"],
                    "audit_event_types": [item["event_type"] for item in events],
                    "fake_target_received": len(fake_target.state.received),
                }
    finally:
        server.should_exit = True
        thread.join(timeout=5)

    return output


def main() -> int:
    result = run_demo()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ticket_status_after"] == "resolved" else 1


if __name__ == "__main__":
    raise SystemExit(main())
