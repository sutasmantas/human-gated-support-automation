"""Phase 6 effect oracle for Relay.

Every case asserts the same six observables named in the frozen admission:
final durable state, ``target_apply_count``, ``target_request_count``, the
ordered attempt-classification history, receipt completeness, and the exit
outcome. The discriminator is that effects are counted at the target, not in
the application: retry theater raises ``apply_count``, correct behaviour raises
only ``request_count``.

Everything above the HTTP transport is Relay's real path — approval gate, tool
registry, ``OutboundHTTPAdapter`` with its host allowlist and redaction, and
the provider-owned durable store.
"""

from __future__ import annotations

import socket
import sqlite3
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
import uvicorn

# counting_target is imported by module name rather than as
# `tests.counting_target`. CI invokes bare `pytest`, which does not put the
# working directory on sys.path the way `python -m pytest` does, so a
# package-qualified import fails to collect there while passing locally.
# pytest puts the test file's own directory on sys.path, so this resolves.
from counting_target import (
    CountingTargetState,
    counting_transport,
    create_counting_target,
)
from fastapi.testclient import TestClient

from support_desk.config import Settings
from support_desk.effects import effect_idempotency_key
from support_desk.main import create_app
from support_desk.outbound import OutboundHTTPAdapter
from support_desk.store import TicketStore

RENEWAL_SUBJECT = "Renewal failed — service at risk"
NOTIFICATION_DESTINATION = "tool:send_notification"
PUBLIC_ADDRESS = "93.184.216.34"


def resolver_for(address: str):
    def resolve(*args: object, **kwargs: object) -> list[tuple]:
        del args, kwargs
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]

    return resolve


def relay_settings(tmp_path: Path, **overrides: object) -> Settings:
    return Settings(
        data_dir=tmp_path / "runtime",
        automation_provider="local",
        notification_webhook_url="https://counted.example.test/webhook/counted",
        outbound_allowed_hosts="counted.example.test",
        **overrides,
    )


@contextmanager
def counted_relay(
    configured: Settings,
    state: CountingTargetState,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """Relay's real stack wired to the idempotency-aware counting target."""

    with TestClient(create_counting_target(state)) as fake:
        adapter = OutboundHTTPAdapter(
            configured,
            transport=counting_transport(fake),
            resolver=resolver_for(PUBLIC_ADDRESS),
        )
        real_send = adapter.send

        def send_through_target(self, payload, *, idempotency_key):
            del self
            return real_send(payload, idempotency_key=idempotency_key)

        monkeypatch.setattr(OutboundHTTPAdapter, "send", send_through_target)
        with TestClient(create_app(configured)) as client:
            yield client


def renewal_ticket(client: TestClient) -> dict:
    return next(
        ticket
        for ticket in client.get("/api/tickets").json()
        if ticket["subject"] == RENEWAL_SUBJECT
    )


def notification_action(ticket: dict) -> dict:
    return next(
        action for action in ticket["actions"] if action["tool_name"] == "send_notification"
    )


def durable_record(configured: Settings) -> tuple[sqlite3.Row, list[sqlite3.Row]]:
    """Read the provider-owned record for the externally visible effect."""

    connection = sqlite3.connect(configured.delivery_sqlite_path)
    connection.row_factory = sqlite3.Row
    try:
        action = connection.execute(
            "SELECT * FROM delivery_actions WHERE destination = ?",
            (NOTIFICATION_DESTINATION,),
        ).fetchone()
        assert action is not None, "the notification effect was never registered"
        attempts = connection.execute(
            "SELECT * FROM delivery_attempts WHERE action_id = ? ORDER BY sequence",
            (action["id"],),
        ).fetchall()
    finally:
        connection.close()
    return action, attempts


def assert_receipts_are_complete(attempts: list[sqlite3.Row]) -> None:
    """Every attempt must be self-describing evidence, not a bare status."""

    for attempt in attempts:
        assert attempt["classification"], "attempt has no classification"
        assert attempt["retryable"] in (0, 1)
        assert attempt["latency_ms"] >= 0
        assert attempt["request_json"] not in (None, "", "{}")
        assert attempt["correlation_id"]
        assert attempt["created_at"]
        # A receipt records either what came back or why nothing did.
        assert (attempt["response_json"] not in (None, "", "{}")) or attempt["error"]


def assert_case(
    *,
    state: CountingTargetState,
    action: sqlite3.Row,
    attempts: list[sqlite3.Row],
    final_state: str,
    apply_count: int,
    request_count: int,
    classifications: list[str],
    attempt_count: int,
    cycle: int,
) -> None:
    assert action["state"] == final_state
    assert state.apply_count == apply_count
    assert state.request_count == request_count
    assert [item["classification"] for item in attempts] == classifications
    assert action["attempt_count"] == attempt_count
    assert action["cycle"] == cycle
    assert_receipts_are_complete(attempts)
    # The effect identity never changes across attempts, which is what makes a
    # duplicate apply impossible rather than merely unlikely.
    assert len(state.distinct_keys) <= 1


# --------------------------------------------------------------------------
# Case 1 — timeout before apply, then success
# --------------------------------------------------------------------------


def test_case_1_timeout_before_apply_then_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = CountingTargetState(script=["timeout_before_apply", "apply"])
    configured = relay_settings(tmp_path)
    with counted_relay(configured, state, monkeypatch) as client:
        ticket_id = renewal_ticket(client)["id"]
        first = client.post(f"/api/tickets/{ticket_id}/approve").json()
        assert first["status"] == "action_failed"

        retried = client.post(f"/api/tickets/{ticket_id}/retry").json()
        assert retried["status"] == "resolved"

    action, attempts = durable_record(configured)
    assert_case(
        state=state,
        action=action,
        attempts=attempts,
        final_state="delivered",
        apply_count=1,
        request_count=2,
        classifications=["network_error", "success"],
        attempt_count=2,
        cycle=1,
    )


# --------------------------------------------------------------------------
# Case 2 — duplicate submit with the same key and payload
# --------------------------------------------------------------------------


def test_case_2_duplicate_submit_adds_no_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = CountingTargetState()
    configured = relay_settings(tmp_path)
    with counted_relay(configured, state, monkeypatch) as client:
        ticket = renewal_ticket(client)
        ticket_id = ticket["id"]
        assert client.post(f"/api/tickets/{ticket_id}/approve").json()["status"] == "resolved"
        after_first = state.snapshot()

        # Product layer: a second approval is a no-op for the reviewer.
        assert client.post(f"/api/tickets/{ticket_id}/approve").json()["status"] == "resolved"

        # Provider layer: re-entering with the identical key and payload
        # returns the durable record without firing anything.
        store: TicketStore = client.app.state.store
        action_payload = notification_action(client.get(f"/api/tickets/{ticket_id}").json())
        key = effect_idempotency_key(
            ticket_id=ticket_id,
            action_id=action_payload["id"],
            tool_name=action_payload["tool_name"],
            arguments=action_payload["arguments"],
        )
        replayed = store.gateway.execute(
            idempotency_key=key,
            destination=NOTIFICATION_DESTINATION,
            payload={
                "ticket_id": ticket_id,
                "action_id": action_payload["id"],
                "tool_name": action_payload["tool_name"],
                "arguments": action_payload["arguments"],
            },
            correlation_id=ticket_id,
            effect=lambda: pytest.fail("a terminal action must never re-fire its effect"),
        )
        assert replayed.executed is False
        assert replayed.succeeded is True

    assert state.snapshot() == after_first
    action, attempts = durable_record(configured)
    assert_case(
        state=state,
        action=action,
        attempts=attempts,
        final_state="delivered",
        apply_count=1,
        request_count=1,
        classifications=["success"],
        attempt_count=1,
        cycle=1,
    )


# --------------------------------------------------------------------------
# Case 4 — crash before the request reaches the target
# --------------------------------------------------------------------------


def test_case_4_crash_before_request_reaches_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = CountingTargetState()
    configured = relay_settings(tmp_path)

    with TestClient(create_counting_target(state)) as fake:
        adapter = OutboundHTTPAdapter(
            configured,
            transport=counting_transport(fake),
            resolver=resolver_for(PUBLIC_ADDRESS),
        )
        real_send = adapter.send

        def die_before_sending(self, payload, *, idempotency_key):
            del self, payload, idempotency_key
            # BaseException, so it is not normalised into a receipt: the row
            # stays `running`, exactly as an abrupt worker death leaves it.
            raise KeyboardInterrupt("worker killed before the request left the client")

        with TestClient(create_app(configured)) as client:
            ticket_id = renewal_ticket(client)["id"]

        # Drive `approve` directly, the same call the endpoint makes. Going
        # through ASGI would repackage the interrupt into an exception group
        # and obscure which layer died.
        monkeypatch.setattr(OutboundHTTPAdapter, "send", die_before_sending)
        dying = TicketStore(configured)
        try:
            with pytest.raises(KeyboardInterrupt):
                dying.approve(ticket_id)
        finally:
            dying.close()

        stranded, _ = durable_record(configured)
        assert stranded["state"] == "running"
        assert state.request_count == 0

        def send_through_target(self, payload, *, idempotency_key):
            del self
            return real_send(payload, idempotency_key=idempotency_key)

        monkeypatch.setattr(OutboundHTTPAdapter, "send", send_through_target)
        restarted = TicketStore(configured)
        try:
            assert restarted.approve(ticket_id).status == "resolved"
        finally:
            restarted.close()

    action, attempts = durable_record(configured)
    assert_case(
        state=state,
        action=action,
        attempts=attempts,
        final_state="delivered",
        apply_count=1,
        request_count=1,
        classifications=["worker_interrupted", "success"],
        attempt_count=2,
        cycle=1,
    )


# --------------------------------------------------------------------------
# Cases 5, 6 and 7 — exhaustion, terminality, and replay
# --------------------------------------------------------------------------


def test_cases_5_6_7_exhaustion_then_terminal_then_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = CountingTargetState(
        default_behaviour="apply",
        script=["server_error", "server_error", "server_error"],
    )
    configured = relay_settings(tmp_path, max_action_attempts=3)

    with counted_relay(configured, state, monkeypatch) as client:
        ticket_id = renewal_ticket(client)["id"]

        # --- Case 5: retry exhaustion -----------------------------------
        assert client.post(f"/api/tickets/{ticket_id}/approve").json()["status"] == (
            "action_failed"
        )
        assert client.post(f"/api/tickets/{ticket_id}/retry").json()["status"] == (
            "action_failed"
        )
        assert client.post(f"/api/tickets/{ticket_id}/retry").json()["status"] == "dead_letter"

        action, attempts = durable_record(configured)
        assert_case(
            state=state,
            action=action,
            attempts=attempts,
            final_state="dead_letter",
            apply_count=0,
            request_count=3,
            classifications=["server_error", "server_error", "server_error"],
            attempt_count=3,
            cycle=1,
        )
        assert action["last_error"], "an exhausted action must carry an explicit failure receipt"

        # --- Case 6: dead letter is terminal ----------------------------
        # The product refuses another operator retry...
        assert client.post(f"/api/tickets/{ticket_id}/retry").status_code == 409
        # ...and the provider refuses even when the consumer re-enters.
        store: TicketStore = client.app.state.store
        store.approve(ticket_id)
        action, attempts = durable_record(configured)
        assert_case(
            state=state,
            action=action,
            attempts=attempts,
            final_state="dead_letter",
            apply_count=0,
            request_count=3,
            classifications=["server_error", "server_error", "server_error"],
            attempt_count=3,
            cycle=1,
        )

        # --- Case 7: replay opens a new cycle ---------------------------
        action_payload = notification_action(client.get(f"/api/tickets/{ticket_id}").json())
        key = effect_idempotency_key(
            ticket_id=ticket_id,
            action_id=action_payload["id"],
            tool_name=action_payload["tool_name"],
            arguments=action_payload["arguments"],
        )
        store.gateway.replay(key, correlation_id=ticket_id)
        assert store.approve(ticket_id).status == "resolved"

    action, attempts = durable_record(configured)
    assert_case(
        state=state,
        action=action,
        attempts=attempts,
        final_state="delivered",
        apply_count=1,
        request_count=4,
        classifications=[
            "server_error",
            "server_error",
            "server_error",
            "success",
        ],
        attempt_count=1,
        cycle=2,
    )
    assert attempts[-1]["cycle"] == 2
    assert attempts[-1]["cycle_attempt"] == 1


# --------------------------------------------------------------------------
# Case 3 — crash after effect, before receipt (load bearing)
# --------------------------------------------------------------------------


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@contextmanager
def serving(app, port: int) -> Iterator[None]:
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started:
        if time.monotonic() > deadline:
            raise TimeoutError("counting target did not start")
        time.sleep(0.05)
    try:
        yield
    finally:
        server.should_exit = True
        thread.join(timeout=20)


def test_case_3_crash_after_effect_before_receipt(tmp_path: Path) -> None:
    """The composition must not re-apply an effect it already caused.

    A real subprocess is killed while the target holds the connection open,
    after the effect is committed and before the receipt is written. Nothing
    here is mocked: a genuine OS process dies over genuine loopback HTTP.
    """

    state = CountingTargetState(default_behaviour="apply", script=["apply_then_hang"])
    port = free_port()
    webhook = f"http://127.0.0.1:{port}/webhook/counted"
    configured = Settings(
        data_dir=tmp_path / "runtime",
        automation_provider="local",
        notification_webhook_url=webhook,
        outbound_allowed_hosts="127.0.0.1",
        outbound_allow_private_networks=True,
        outbound_read_timeout_seconds=60,
        outbound_connect_timeout_seconds=10,
    )

    with serving(create_counting_target(state), port):
        with TestClient(create_app(configured)) as client:
            ticket_id = renewal_ticket(client)["id"]

        worker = subprocess.Popen(  # noqa: S603
            [
                sys.executable,
                "-m",
                "tests.crash_worker",
                str(configured.data_dir),
                ticket_id,
                webhook,
            ],
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        try:
            deadline = time.monotonic() + 45
            while state.apply_count < 1:
                if worker.poll() is not None:
                    raise AssertionError(
                        f"worker exited early with code {worker.returncode}"
                    )
                if time.monotonic() > deadline:
                    raise TimeoutError("the target never applied the effect")
                time.sleep(0.05)
            # The effect is now durable at the target. Kill the worker before
            # it can record a receipt.
            worker.kill()
        finally:
            worker.wait(timeout=30)

        assert worker.returncode != 0, "the worker must have been killed, not exited cleanly"

        stranded, _ = durable_record(configured)
        assert stranded["state"] == "running", "the crash must leave an unresolved attempt"
        assert state.apply_count == 1
        assert state.request_count == 1

        # Restart and re-approve. The target recognises the unchanged
        # idempotency key and answers 409, so the effect is not repeated.
        restarted = TicketStore(configured)
        try:
            assert restarted.approve(ticket_id).status == "resolved"
        finally:
            restarted.close()

    action, attempts = durable_record(configured)
    assert_case(
        state=state,
        action=action,
        attempts=attempts,
        final_state="already_applied",
        apply_count=1,
        request_count=2,
        classifications=["worker_interrupted", "already_applied"],
        attempt_count=2,
        cycle=1,
    )


# --------------------------------------------------------------------------
# Retry theater control
# --------------------------------------------------------------------------


def test_regenerated_idempotency_key_would_duplicate_the_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prove the oracle can actually see a duplicate effect.

    If the composition derived a fresh key per attempt — the retry-theater
    failure mode — the target could not recognise the repeat and would apply
    twice. This drives the target directly to show that ``apply_count`` is a
    real discriminator and not an assertion that can never fail.
    """

    state = CountingTargetState()
    with TestClient(create_counting_target(state)) as fake:
        for attempt in range(2):
            response = fake.post(
                "/webhook/counted",
                json={"ticket": "CS-DEMO"},
                headers={"Idempotency-Key": f"regenerated-key-{attempt}"},
            )
            assert response.status_code == 200

        stable = "stable-key-000001"
        assert fake.post(
            "/webhook/counted", json={"ticket": "CS-DEMO"}, headers={"Idempotency-Key": stable}
        ).status_code == 200
        assert fake.post(
            "/webhook/counted", json={"ticket": "CS-DEMO"}, headers={"Idempotency-Key": stable}
        ).status_code == 409

    assert state.request_count == 4
    # Two applies from regenerated keys, one from the stable key.
    assert state.apply_count == 3
