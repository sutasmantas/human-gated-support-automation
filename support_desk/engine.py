from __future__ import annotations

import json
import re
from dataclasses import dataclass

import httpx

from support_desk.config import Settings
from support_desk.schemas import Action, Source, TicketCreate

POLICIES = [
    Source(
        title="Enterprise billing policy",
        section="Grace periods",
        excerpt=(
            "Enterprise accounts may receive one seven-day service hold after a failed renewal "
            "when Finance confirms that a payment update is in progress."
        ),
        score=0.98,
    ),
    Source(
        title="Failed renewal playbook",
        section="Escalation and communication",
        excerpt=(
            "Support must create a renewal case, notify Billing Operations and obtain human "
            "approval before promising continued service to an account above 25,000 USD ARR."
        ),
        score=0.94,
    ),
    Source(
        title="Identity support guide",
        section="SSO setup",
        excerpt="Enterprise SSO requests route to Technical Support with workspace metadata.",
        score=0.91,
    ),
]


@dataclass(frozen=True)
class AutomationResult:
    intent: str
    priority: str
    sentiment: str
    route: str
    confidence: float
    risk_reason: str
    draft: str
    sources: list[Source]
    actions: list[Action]


class LocalAutomation:
    name = "local"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def process(self, ticket: TicketCreate) -> AutomationResult:
        text = f"{ticket.subject} {ticket.body}".lower()
        if any(word in text for word in ("renewal", "payment", "invoice", "billing")):
            intent, route = "Failed renewal", "Billing Ops"
            sources = POLICIES[:2]
        elif any(word in text for word in ("sso", "saml", "metadata")):
            intent, route = "SSO configuration", "Technical Support"
            sources = [POLICIES[2]]
        else:
            intent, route = "General support", "Customer Support"
            sources = []

        urgent_language = bool(
            re.search(r"\b(urgent|suspend|outage|blocked|cannot lose|service at risk)\b", text)
        )
        priority = (
            "Urgent"
            if urgent_language or ticket.arr_usd >= self.settings.approval_arr_threshold
            else "Normal"
        )
        sentiment = "Concerned" if urgent_language else "Neutral"
        confidence = 0.96 if intent != "General support" else 0.72
        needs_hold = intent == "Failed renewal"
        risk_reason = (
            f"{ticket.company} has {ticket.active_users} active users and "
            f"{ticket.arr_usd:,} USD ARR. Human approval is required before account changes."
            if priority == "Urgent"
            else "No high-risk language or account threshold was detected."
        )
        if intent == "Failed renewal":
            draft = (
                f"Hi {ticket.customer_name.split()[0]} — I checked the renewal issue. "
                "Your workspace can remain active while the payment method is updated once the "
                "seven-day billing hold below is approved. Your finance administrator can retry "
                "the renewal from Billing → Payment methods."
            )
        elif intent == "SSO configuration":
            draft = (
                f"Hi {ticket.customer_name.split()[0]} — I can help with the SSO setup. "
                "Please send the workspace ID and identity-provider metadata URL so Technical "
                "Support can validate the configuration."
            )
        else:
            draft = (
                f"Hi {ticket.customer_name.split()[0]} — thanks for the details. "
                "I routed this request to Customer Support for review."
            )

        actions = [
            Action(
                id="billing-hold",
                kind="billing_hold",
                label="Apply 7-day billing hold",
                system="Local billing adapter",
                status="pending",
            ),
            Action(
                id="case-update",
                kind="case_update",
                label="Update renewal case",
                system="Local CRM adapter",
                status="pending",
            ),
            Action(
                id="notify",
                kind="notification",
                label="Notify billing channel",
                system="Outbox webhook adapter",
                status="pending",
            ),
        ]
        if not needs_hold:
            actions = actions[1:]
        return AutomationResult(
            intent=intent,
            priority=priority,
            sentiment=sentiment,
            route=route,
            confidence=confidence,
            risk_reason=risk_reason,
            draft=draft,
            sources=sources,
            actions=actions,
        )


class OpenAIAutomation(LocalAutomation):
    name = "openai-compatible"

    def process(self, ticket: TicketCreate) -> AutomationResult:
        base = super().process(ticket)
        if not self.settings.llm_base_url or not self.settings.llm_model:
            raise RuntimeError("OpenAI-compatible mode requires a base URL and model.")
        prompt = {
            "subject": ticket.subject,
            "body": ticket.body,
            "account": {
                "company": ticket.company,
                "arr_usd": ticket.arr_usd,
                "active_users": ticket.active_users,
            },
            "policies": [source.model_dump() for source in base.sources],
        }
        headers = {"Content-Type": "application/json"}
        if self.settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self.settings.llm_api_key}"
        response = httpx.post(
            f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
            headers=headers,
            timeout=45,
            json={
                "model": self.settings.llm_model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Return JSON with intent, priority, sentiment, route, confidence, "
                            "risk_reason and draft. Ground the draft only in supplied policies. "
                            "Never claim an action has completed."
                        ),
                    },
                    {"role": "user", "content": json.dumps(prompt)},
                ],
            },
        )
        response.raise_for_status()
        payload = json.loads(response.json()["choices"][0]["message"]["content"])
        return AutomationResult(
            intent=str(payload["intent"]),
            priority=str(payload["priority"]),
            sentiment=str(payload["sentiment"]),
            route=str(payload["route"]),
            confidence=float(payload["confidence"]),
            risk_reason=str(payload["risk_reason"]),
            draft=str(payload["draft"]),
            sources=base.sources,
            actions=base.actions,
        )


def create_automation(settings: Settings) -> LocalAutomation:
    if settings.automation_provider == "openai-compatible":
        return OpenAIAutomation(settings)
    return LocalAutomation(settings)
