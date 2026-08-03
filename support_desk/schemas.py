from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class TicketCreate(BaseModel):
    subject: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=10, max_length=5000)
    customer_name: str = Field(min_length=2, max_length=120)
    company: str = Field(min_length=2, max_length=120)
    arr_usd: int = Field(default=0, ge=0)
    active_users: int = Field(default=1, ge=1)


class Action(BaseModel):
    id: str
    kind: str
    label: str
    system: str
    status: str
    result: str | None = None
    attempts: int = 0
    last_error: str | None = None
    tool_name: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    risk_class: Literal["read_only", "write", "irreversible"] = "write"
    externally_visible: bool = True
    tool_call_id: str | None = None


class Source(BaseModel):
    title: str
    section: str
    excerpt: str
    score: float


class Ticket(BaseModel):
    id: str
    subject: str
    body: str
    customer_name: str
    company: str
    arr_usd: int
    active_users: int
    intent: str
    priority: str
    sentiment: str
    route: str
    confidence: float
    risk_reason: str
    draft: str
    status: str
    sources: list[Source]
    actions: list[Action]
    created_at: datetime
    approved_at: datetime | None = None


class Stats(BaseModel):
    tickets: int
    needs_approval: int
    resolved: int
    automation_provider: str


class WorkflowStep(BaseModel):
    id: str
    name: str
    kind: str
    description: str


class DecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    note: str = Field(default="", max_length=500)


class WorkflowEvent(BaseModel):
    id: int
    ticket_id: str
    event_type: str
    detail: str
    created_at: datetime


class ToolCall(BaseModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,79}$")
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    arguments: dict[str, Any]


class ToolCallRecord(BaseModel):
    id: str
    ticket_id: str
    sequence: int
    tool_name: str
    arguments: dict[str, Any]
    risk_class: str
    externally_visible: bool
    status: str
    attempts: int
    result: dict[str, Any] | None = None
    error: str | None = None


class ToolDescription(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    risk_class: Literal["read_only", "write", "irreversible"]
    externally_visible: bool
