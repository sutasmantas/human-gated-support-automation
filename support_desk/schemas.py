from __future__ import annotations

from datetime import datetime

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
