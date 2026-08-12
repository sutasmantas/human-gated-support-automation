from __future__ import annotations

import json
import re
from dataclasses import dataclass

from proofgrid_provider import ChatRequest, Message, OpenAICompatibleProvider
from proofgrid_structured_output import parse

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
    Source(
        title="Billing operations handbook",
        section="Invoice corrections",
        excerpt=(
            "Tax-identifier and legal-entity corrections must be verified before a replacement "
            "invoice is issued by Billing Operations."
        ),
        score=0.93,
    ),
    Source(
        title="Data delivery runbook",
        section="Completed exports",
        excerpt=(
            "After export delivery is verified, close the operations case and notify the "
            "customer's account team."
        ),
        score=0.95,
    ),
]

AUTOMATION_SCHEMA = {
    "type": "object",
    "required": [
        "intent",
        "priority",
        "sentiment",
        "route",
        "confidence",
        "risk_reason",
        "draft",
    ],
    "additionalProperties": False,
    "properties": {
        "intent": {"type": "string"},
        "priority": {"type": "string"},
        "sentiment": {"type": "string"},
        "route": {"type": "string"},
        "confidence": {"type": "number"},
        "risk_reason": {"type": "string"},
        "draft": {"type": "string"},
    },
}


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
        if any(word in text for word in ("invoice", "vat", "tax id")):
            intent, route = "Invoice correction", "Billing Ops"
            sources = [POLICIES[3]]
        elif any(word in text for word in ("renewal", "payment", "service at risk")):
            intent, route = "Failed renewal", "Billing Ops"
            sources = POLICIES[:2]
        elif any(word in text for word in ("sso", "saml", "metadata")):
            intent, route = "SSO configuration", "Technical Support"
            sources = [POLICIES[2]]
        elif any(word in text for word in ("export", "delivered", "data delivery")):
            intent, route = "Completed export", "Data Operations"
            sources = [POLICIES[4]]
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
        elif intent == "Invoice correction":
            draft = (
                f"Hi {ticket.customer_name.split()[0]} — I routed the invoice correction to "
                "Billing Operations. Please confirm the VAT ID and legal entity that should "
                "appear on the replacement invoice."
            )
        elif intent == "Completed export":
            draft = (
                f"Hi {ticket.customer_name.split()[0]} — the historical export is marked as "
                "delivered. I can close the operations case and notify your account team."
            )
        else:
            draft = (
                f"Hi {ticket.customer_name.split()[0]} — thanks for the details. "
                "I routed this request to Customer Support for review."
            )

        actions = []
        if needs_hold:
            actions.append(
                Action(
                    id="billing-hold",
                    kind="billing_hold",
                    label="Apply 7-day billing hold",
                    system="Local billing adapter",
                    status="pending",
                )
            )
        case_labels = {
            "Failed renewal": "Update renewal case",
            "Invoice correction": "Open invoice correction",
            "SSO configuration": "Update technical support case",
            "Completed export": "Close export delivery case",
            "General support": "Update support case",
        }
        notification_labels = {
            "Failed renewal": "Notify billing channel",
            "Invoice correction": "Notify billing owner",
            "SSO configuration": "Notify technical support",
            "Completed export": "Notify account team",
            "General support": "Notify support owner",
        }
        actions.extend(
            [
            Action(
                id="case-update",
                kind="case_update",
                label=case_labels[intent],
                system="Local CRM adapter",
                status="pending",
            ),
            Action(
                id="notify",
                kind="notification",
                label=notification_labels[intent],
                system="Outbox webhook adapter",
                status="pending",
            ),
            ]
        )
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
        provider = OpenAICompatibleProvider(
            self.settings.llm_base_url,
            self.settings.llm_api_key,
        )
        completion = provider.complete(
            ChatRequest(
                messages=(
                    Message(
                        "system",
                        (
                            "Return JSON with intent, priority, sentiment, route, confidence, "
                            "risk_reason and draft. Ground the draft only in supplied policies. "
                            "Never claim an action has completed."
                        ),
                    ),
                    Message("user", json.dumps(prompt)),
                ),
                model=self.settings.llm_model,
                temperature=0,
                response_format={"type": "json_object"},
            ),
            timeout=45,
        )
        payload = parse(completion.text, AUTOMATION_SCHEMA)
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
