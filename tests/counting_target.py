"""An idempotency-key-stateful counting target for the Phase 6 effect oracle.

`support_desk.fake_target` records every request it receives but never dedupes
by `Idempotency-Key`, so it cannot distinguish "the client retried" from "the
effect was applied twice". This target separates the two counters:

- ``request_count`` — every request that reached the target;
- ``apply_count``  — effects actually applied.

A correct bounded-retry composition raises only ``request_count``. Retry theater
— re-deriving a fresh idempotency key on each attempt — raises ``apply_count``,
because the target has no way to recognise the repeat.

The target deliberately does **not** collapse duplicates silently. It appends to
an ordered ``applied`` log and only answers 409 when it recognises a key it has
already applied, so a duplicated effect is observable rather than hidden.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import anyio
import httpx
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, Response
from fastapi.testclient import TestClient

# Returned by the app and translated into a client-side timeout by the bridge.
TIMEOUT_SENTINEL_STATUS = 599

BEHAVIOURS = frozenset(
    {
        "apply",
        "apply_then_hang",
        "server_error",
        "rate_limit",
        "client_error",
        "timeout_before_apply",
    }
)

#: How long ``apply_then_hang`` stalls after committing the effect. Long enough
#: for the crash test to kill the caller mid-flight, short enough to bound the
#: case if the kill fails.
HANG_SECONDS = 30.0


@dataclass
class CountingTargetState:
    """Observable target-side state for one fault case."""

    default_behaviour: str = "apply"
    script: list[str] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)
    applied: list[str] = field(default_factory=list)

    def next_behaviour(self) -> str:
        behaviour = self.script.pop(0) if self.script else self.default_behaviour
        if behaviour not in BEHAVIOURS:
            raise ValueError(f"Unknown counting-target behaviour: {behaviour!r}")
        return behaviour

    @property
    def request_count(self) -> int:
        return len(self.requests)

    @property
    def apply_count(self) -> int:
        return len(self.applied)

    @property
    def distinct_keys(self) -> set[str]:
        return {item["idempotency_key"] for item in self.requests}

    def snapshot(self) -> dict[str, Any]:
        return {
            "request_count": self.request_count,
            "apply_count": self.apply_count,
            "distinct_keys": sorted(self.distinct_keys),
            "applied": list(self.applied),
        }


def create_counting_target(state: CountingTargetState) -> FastAPI:
    app = FastAPI(title="Phase 6 counting target", version="1.0.0")
    app.state.counting = state

    @app.post("/webhook/counted")
    async def counted(
        request: Request,
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> Response:
        payload: dict[str, Any] = await request.json()
        behaviour = state.next_behaviour()
        state.requests.append(
            {
                "idempotency_key": idempotency_key,
                "behaviour": behaviour,
                "payload": payload,
            }
        )

        if behaviour == "timeout_before_apply":
            # The request arrived but the effect is not applied, mirroring a
            # target that is slow before it commits anything.
            return JSONResponse({"status": "too_slow"}, status_code=TIMEOUT_SENTINEL_STATUS)
        if behaviour == "server_error":
            return JSONResponse({"status": "unavailable"}, status_code=500)
        if behaviour == "rate_limit":
            return JSONResponse({"status": "slow_down"}, status_code=429)
        if behaviour == "client_error":
            return JSONResponse({"status": "invalid_request"}, status_code=400)

        if idempotency_key and idempotency_key in state.applied:
            return JSONResponse({"status": "already_applied"}, status_code=409)

        state.applied.append(idempotency_key)

        if behaviour == "apply_then_hang":
            # The effect is committed, but the caller never learns that. This
            # is the crash-after-effect window the oracle has to close.
            await anyio.sleep(HANG_SECONDS)

        return JSONResponse({"status": "applied", "sequence": len(state.applied)})

    return app


def counting_transport(fake: TestClient) -> httpx.MockTransport:
    """Bridge the real outbound client onto the counting target.

    Everything above the transport stays real: destination validation, secret
    resolution, header construction, redaction, and status classification.
    """

    def bridge(request: httpx.Request) -> httpx.Response:
        response = fake.post(
            request.url.path,
            content=request.content,
            headers=dict(request.headers),
        )
        if response.status_code == TIMEOUT_SENTINEL_STATUS:
            raise httpx.ReadTimeout("counting target exceeded the read timeout", request=request)
        return httpx.Response(
            response.status_code,
            content=response.content,
            headers=dict(response.headers),
            request=request,
        )

    return httpx.MockTransport(bridge)
