from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

Scenario = Literal["success", "conflict", "timeout", "rate-limit", "terminal", "invalid"]


def create_fake_target() -> FastAPI:
    app = FastAPI(title="Relay local outbound fake", version="1.0.0")
    app.state.received = []

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/webhook/{scenario}")
    async def webhook(
        scenario: Scenario,
        request: Request,
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> Response:
        payload: dict[str, Any] = await request.json()
        app.state.received.append(
            {
                "scenario": scenario,
                "idempotency_key": idempotency_key,
                "payload": payload,
            }
        )
        if scenario == "timeout":
            await asyncio.sleep(0.25)
        if scenario == "conflict":
            return JSONResponse(
                {"status": "already_applied", "secret": "fake-response-secret"},
                status_code=409,
            )
        if scenario == "rate-limit":
            return JSONResponse({"status": "slow_down"}, status_code=429)
        if scenario == "terminal":
            return JSONResponse({"status": "invalid_request"}, status_code=400)
        if scenario == "invalid":
            return PlainTextResponse("not-json", status_code=200)
        return JSONResponse(
            {
                "status": "applied",
                "echo": payload,
                "secret": "fake-response-secret",
            }
        )

    return app


app = create_fake_target()
