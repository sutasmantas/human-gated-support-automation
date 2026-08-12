from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from proofgrid_provider import TransportError
from proofgrid_structured_output import SchemaError

from support_desk.config import Settings
from support_desk.engine import OpenAIAutomation
from support_desk.schemas import TicketCreate


def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "runtime",
        automation_provider="openai-compatible",
        llm_base_url="https://llm.example.test/v1",
        llm_api_key="secret",
        llm_model="test-model",
    )


def ticket() -> TicketCreate:
    return TicketCreate(
        subject="Renewal failed for test account",
        body="Our renewal failed and service is at risk while finance updates payment.",
        customer_name="Alex Example",
        company="Example Co",
        arr_usd=48_000,
        active_users=40,
    )


OUTPUT = {
    "intent": "Failed renewal",
    "priority": "Urgent",
    "sentiment": "Concerned",
    "route": "Billing Ops",
    "confidence": 0.96,
    "risk_reason": "Human approval is required.",
    "draft": "We are reviewing the failed renewal.",
}


class FakeResponse:
    def __init__(self, content: str) -> None:
        self.content = content

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(
            {"choices": [{"message": {"content": self.content}}]}
        ).encode("utf-8")


@pytest.mark.parametrize(
    "content",
    [
        json.dumps(OUTPUT),
        f"```json\n{json.dumps(OUTPUT)}\n```",
        json.dumps(OUTPUT) + "\nThe requested object is above.",
    ],
)
def test_relay_consumes_packaged_provider_and_structured_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    content: str,
) -> None:
    captured: dict[str, object] = {}

    def open_response(wire: urllib.request.Request, *, timeout: float) -> FakeResponse:
        captured["url"] = wire.full_url
        captured["headers"] = dict(wire.header_items())
        captured["request"] = json.loads(bytes(wire.data or b"").decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse(content)

    monkeypatch.setattr("proofgrid_provider.core.urllib.request.urlopen", open_response)
    result = OpenAIAutomation(settings(tmp_path)).process(ticket())

    assert result.intent == OUTPUT["intent"]
    assert result.confidence == OUTPUT["confidence"]
    assert result.sources
    assert result.actions
    assert captured["url"] == "https://llm.example.test/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer secret"
    assert captured["timeout"] == 45
    request = captured["request"]
    assert request["model"] == "test-model"
    assert request["temperature"] == 0
    assert request["response_format"] == {"type": "json_object"}
    assert [message["role"] for message in request["messages"]] == ["system", "user"]
    assert "supplied policies" in request["messages"][0]["content"]
    assert "Example Co" in request["messages"][1]["content"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda output: {key: value for key, value in output.items() if key != "draft"},
        lambda output: {**output, "extra": True},
        lambda output: {**output, "confidence": "high"},
    ],
)
def test_relay_refuses_wrong_shaped_model_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation,
) -> None:
    content = json.dumps(mutation(OUTPUT))
    monkeypatch.setattr(
        "proofgrid_provider.core.urllib.request.urlopen",
        lambda *_args, **_kwargs: FakeResponse(content),
    )

    with pytest.raises(SchemaError) as caught:
        OpenAIAutomation(settings(tmp_path)).process(ticket())
    assert caught.value.stage == "validate"


def test_relay_receives_normalized_provider_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def offline(*_args: object, **_kwargs: object) -> FakeResponse:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("proofgrid_provider.core.urllib.request.urlopen", offline)
    with pytest.raises(TransportError, match="offline"):
        OpenAIAutomation(settings(tmp_path)).process(ticket())

