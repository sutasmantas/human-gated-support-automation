from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from deliveryguard.identifiers import normalize_correlation_id
from deliveryguard.store import DeliveryStore

from support_desk.config import Settings
from support_desk.effects import DurableEffectGateway, effect_idempotency_key
from support_desk.engine import AutomationResult
from support_desk.schemas import (
    Action,
    Source,
    Stats,
    Ticket,
    TicketCreate,
    ToolCall,
    ToolCallRecord,
    WorkflowEvent,
)
from support_desk.tools import (
    ToolContext,
    ToolPlanner,
    ToolRegistry,
    ToolRetryableError,
    ToolTerminalError,
    ToolValidationError,
    create_default_registry,
    create_planner,
)


class TicketStore:
    def __init__(
        self,
        settings: Settings,
        *,
        planner: ToolPlanner | None = None,
        registry: ToolRegistry | None = None,
    ) -> None:
        settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings = settings
        self.connection = sqlite3.connect(settings.sqlite_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.registry = registry or create_default_registry()
        self.planner = planner or create_planner(settings)
        # Idempotency, attempt receipts, dead-lettering, crash recovery, and
        # replay are provider-owned. Relay only paces the attempts.
        self.deliveries = DeliveryStore(settings.delivery_sqlite_path)
        self.gateway = DurableEffectGateway(
            self.deliveries,
            max_attempts=settings.max_action_attempts,
        )
        self._initialize()

    def _initialize(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tickets (
                id TEXT PRIMARY KEY,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                customer_name TEXT NOT NULL,
                company TEXT NOT NULL,
                arr_usd INTEGER NOT NULL,
                active_users INTEGER NOT NULL,
                intent TEXT NOT NULL,
                priority TEXT NOT NULL,
                sentiment TEXT NOT NULL,
                route TEXT NOT NULL,
                confidence REAL NOT NULL,
                risk_reason TEXT NOT NULL,
                draft TEXT NOT NULL,
                status TEXT NOT NULL,
                sources_json TEXT NOT NULL,
                actions_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                approved_at TEXT
            );
            CREATE TABLE IF NOT EXISTS billing_holds (
                ticket_id TEXT PRIMARY KEY,
                company TEXT NOT NULL,
                days INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS case_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id TEXT NOT NULL,
                event TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS notification_outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                delivery_status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS workflow_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                detail TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tool_calls (
                id TEXT NOT NULL,
                ticket_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                tool_name TEXT NOT NULL,
                arguments_json TEXT NOT NULL,
                risk_class TEXT NOT NULL,
                externally_visible INTEGER NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                result_json TEXT,
                error TEXT,
                PRIMARY KEY (ticket_id, id)
            );
            CREATE TABLE IF NOT EXISTS mcp_proposals (
                idempotency_key TEXT PRIMARY KEY,
                request_sha256 TEXT NOT NULL,
                ticket_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def count(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM tickets").fetchone()[0])

    def create(self, incoming: TicketCreate, result: AutomationResult) -> Ticket:
        ticket_id = f"CS-{uuid.uuid4().hex[:6].upper()}"
        created_at = datetime.now(UTC)
        status = "needs_approval" if result.priority == "Urgent" else "draft_ready"
        self.connection.execute(
            """
            INSERT INTO tickets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticket_id,
                incoming.subject,
                incoming.body,
                incoming.customer_name,
                incoming.company,
                incoming.arr_usd,
                incoming.active_users,
                result.intent,
                result.priority,
                result.sentiment,
                result.route,
                result.confidence,
                result.risk_reason,
                result.draft,
                status,
                json.dumps([source.model_dump() for source in result.sources]),
                "[]",
                created_at.isoformat(),
                None,
            ),
        )
        self.connection.commit()
        self._event(
            ticket_id,
            "ticket.created",
            f"Routed to {result.route}",
            created_at.isoformat(),
        )
        return self._plan_tools(ticket_id, incoming, result, created_at.isoformat())

    def create_mcp_proposal(
        self,
        incoming: TicketCreate,
        result: AutomationResult,
        idempotency_key: str,
    ) -> tuple[Ticket, bool]:
        request_json = json.dumps(
            incoming.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        request_sha256 = hashlib.sha256(request_json.encode("utf-8")).hexdigest()
        existing = self.connection.execute(
            "SELECT request_sha256, ticket_id FROM mcp_proposals WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if existing:
            if existing["request_sha256"] != request_sha256:
                raise ValueError("Idempotency key was already used for a different request.")
            return self.get(str(existing["ticket_id"])), True

        ticket = self.create(incoming, result)
        try:
            self.connection.execute(
                "INSERT INTO mcp_proposals VALUES (?, ?, ?, ?)",
                (
                    idempotency_key,
                    request_sha256,
                    ticket.id,
                    datetime.now(UTC).isoformat(),
                ),
            )
            self.connection.commit()
        except sqlite3.IntegrityError:
            existing = self.connection.execute(
                "SELECT request_sha256, ticket_id FROM mcp_proposals WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if not existing or existing["request_sha256"] != request_sha256:
                raise ValueError(
                    "Idempotency key was already used for a different request."
                ) from None
            return self.get(str(existing["ticket_id"])), True
        self._event(
            ticket.id,
            "mcp.proposal_created",
            json.dumps(
                {
                    "idempotency_key": idempotency_key,
                    "external_writes_executed": False,
                },
                sort_keys=True,
            ),
            datetime.now(UTC).isoformat(),
        )
        return ticket, False

    def _plan_tools(
        self,
        ticket_id: str,
        incoming: TicketCreate,
        automation: AutomationResult,
        now: str,
    ) -> Ticket:
        try:
            calls = self.planner.plan(incoming, automation, self.registry.describe())
        except (httpx.HTTPError, RuntimeError, KeyError, ValueError) as exc:
            self._event(
                ticket_id,
                "agent.provider_failed",
                json.dumps({"provider": self.planner.name, "error": str(exc)}, sort_keys=True),
                now,
            )
            return self._finish_planning_failure(ticket_id, "provider_failure", now)

        seen: set[str] = set()
        for sequence, call in enumerate(calls, start=1):
            if call.id in seen:
                self._event(
                    ticket_id,
                    "tool.validation_failed",
                    json.dumps({"call_id": call.id, "error": "Duplicate call id."}),
                    now,
                )
                return self._finish_planning_failure(ticket_id, "duplicate_call_id", now)
            seen.add(call.id)
            try:
                tool = self.registry.get(call.name)
                risk_class = tool.risk_class
                externally_visible = tool.externally_visible
            except ToolValidationError:
                risk_class = "unknown"
                externally_visible = False
            self._insert_tool_call(
                ticket_id,
                sequence,
                call,
                risk_class,
                externally_visible,
                "planned",
            )
            self._event(
                ticket_id,
                "tool.planned",
                self._audit_detail(call, risk_class=risk_class),
                now,
            )

        if len(calls) > self.settings.max_tool_steps:
            self.connection.execute(
                "UPDATE tool_calls SET status = 'step_limit_rejected' WHERE ticket_id = ?",
                (ticket_id,),
            )
            self.connection.commit()
            self._event(
                ticket_id,
                "agent.step_limit",
                json.dumps(
                    {"planned_steps": len(calls), "max_tool_steps": self.settings.max_tool_steps},
                    sort_keys=True,
                ),
                now,
            )
            return self._finish_planning_failure(ticket_id, "step_limit", now)

        pending_actions: list[Action] = []
        consumed_legacy_ids: set[str] = set()
        for call in calls:
            try:
                tool, _ = self.registry.validate(
                    call,
                    max_argument_bytes=self.settings.max_tool_argument_bytes,
                )
            except ToolValidationError as exc:
                self._update_tool_call(
                    ticket_id,
                    call.id,
                    status="validation_failed",
                    error=str(exc),
                )
                self._event(
                    ticket_id,
                    "tool.validation_failed",
                    self._audit_detail(call, error=str(exc)),
                    now,
                )
                return self._finish_planning_failure(ticket_id, "validation_failure", now)

            if tool.risk_class == "read_only":
                try:
                    self._event(
                        ticket_id,
                        "tool.attempted",
                        self._audit_detail(call, attempt=1, approval_required=False),
                        now,
                    )
                    result = self.registry.execute(
                        ToolContext(
                            connection=self.connection,
                            settings=self.settings,
                            ticket=self.get(ticket_id),
                            now=now,
                            call_id=call.id,
                        ),
                        call,
                    )
                except (ToolRetryableError, ToolTerminalError, ToolValidationError) as exc:
                    self._update_tool_call(
                        ticket_id,
                        call.id,
                        status="failed",
                        attempts=1,
                        error=str(exc),
                    )
                    self._event(
                        ticket_id,
                        "tool.result",
                        self._audit_detail(call, status="failed", error=str(exc)),
                        now,
                    )
                    return self._finish_planning_failure(ticket_id, "read_failure", now)
                self._update_tool_call(
                    ticket_id,
                    call.id,
                    status="completed",
                    attempts=1,
                    result=result,
                )
                self._event(
                    ticket_id,
                    "tool.result",
                    self._audit_detail(call, status="completed", result=result),
                    now,
                )
                continue

            legacy = self._legacy_action_for_call(
                call,
                automation.actions,
                consumed_legacy_ids,
            )
            if legacy:
                consumed_legacy_ids.add(legacy.id)
            pending_actions.append(
                Action(
                    id=legacy.id if legacy else call.id,
                    kind=legacy.kind if legacy else call.name,
                    label=legacy.label if legacy else tool.label,
                    system=legacy.system if legacy else tool.system,
                    status="pending",
                    tool_name=call.name,
                    arguments=call.arguments,
                    risk_class=tool.risk_class,
                    externally_visible=tool.externally_visible,
                    tool_call_id=call.id,
                )
            )
            self._update_tool_call(ticket_id, call.id, status="awaiting_approval")

        self.connection.execute(
            "UPDATE tickets SET actions_json = ? WHERE id = ?",
            (json.dumps([action.model_dump() for action in pending_actions]), ticket_id),
        )
        self.connection.commit()
        self._event(
            ticket_id,
            "agent.completed",
            json.dumps(
                {
                    "provider": self.planner.name,
                    "state": "awaiting_approval" if pending_actions else "completed",
                    "steps": len(calls),
                },
                sort_keys=True,
            ),
            now,
        )
        return self.get(ticket_id)

    def _finish_planning_failure(self, ticket_id: str, reason: str, now: str) -> Ticket:
        self.connection.execute(
            "UPDATE tickets SET status = 'dead_letter', actions_json = '[]' WHERE id = ?",
            (ticket_id,),
        )
        self.connection.commit()
        self._event(
            ticket_id,
            "agent.completed",
            json.dumps({"state": "dead_letter", "reason": reason}, sort_keys=True),
            now,
        )
        return self.get(ticket_id)

    def list(self) -> list[Ticket]:
        rows = self.connection.execute("SELECT * FROM tickets ORDER BY created_at DESC").fetchall()
        return [self._to_ticket(row) for row in rows]

    def get(self, ticket_id: str) -> Ticket:
        row = self.connection.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if not row:
            raise KeyError(ticket_id)
        return self._to_ticket(row)

    def approve(self, ticket_id: str) -> Ticket:
        ticket = self.get(ticket_id)
        if ticket.status == "resolved":
            return ticket
        if ticket.status == "rejected":
            raise ValueError("A rejected ticket cannot be approved.")
        now = datetime.now(UTC).isoformat()
        if ticket.approved_at is None:
            self._event(
                ticket_id,
                "approval.approved",
                json.dumps(
                    {
                        "message": "Human reviewer approved the proposed reply and side effects.",
                        "calls": [
                            {
                                "call_id": action.tool_call_id,
                                "tool_name": action.tool_name,
                                "arguments": action.arguments,
                                "risk_class": action.risk_class,
                            }
                            for action in ticket.actions
                        ],
                    },
                    sort_keys=True,
                ),
                now,
            )
        completed: list[Action] = []
        terminal_failure = False
        for action in ticket.actions:
            if action.status == "completed":
                completed.append(action)
                continue
            attempt = action.attempts + 1
            if action.tool_call_id:
                self._event(
                    ticket.id,
                    "tool.attempted",
                    json.dumps(
                        {
                            "call_id": action.tool_call_id,
                            "tool_name": action.tool_name,
                            "arguments": action.arguments,
                            "attempt": attempt,
                            "approval_required": True,
                            "approved": True,
                        },
                        sort_keys=True,
                    ),
                    now,
                )
            outcome = self.gateway.execute(
                idempotency_key=effect_idempotency_key(
                    ticket_id=ticket.id,
                    action_id=action.id,
                    tool_name=action.tool_name,
                    arguments=action.arguments,
                ),
                destination=f"tool:{action.tool_name or action.kind}",
                payload={
                    "ticket_id": ticket.id,
                    "action_id": action.id,
                    "tool_name": action.tool_name,
                    "arguments": action.arguments,
                },
                correlation_id=normalize_correlation_id(ticket.id),
                effect=lambda bound=action: self._execute_action(ticket, bound, now),
            )
            attempt = outcome.attempt_count

            if outcome.succeeded:
                result_payload = outcome.result or {
                    "message": f"Effect {outcome.state.value} on an earlier attempt",
                    "delivery_status": outcome.state.value,
                    "receipt_reused": True,
                }
                result = str(
                    result_payload.get("message") or json.dumps(result_payload, sort_keys=True)
                )
                if action.tool_call_id:
                    self._update_tool_call(
                        ticket.id,
                        action.tool_call_id,
                        status="completed",
                        attempts=attempt,
                        result=result_payload,
                        error=None,
                    )
                    self._event(
                        ticket.id,
                        "tool.result",
                        json.dumps(
                            {
                                "call_id": action.tool_call_id,
                                "tool_name": action.tool_name,
                                "status": "completed",
                                "attempt": attempt,
                                "result": result_payload,
                            },
                            sort_keys=True,
                        ),
                        now,
                    )
                completed.append(
                    action.model_copy(
                        update={
                            "status": "completed",
                            "result": result,
                            "attempts": attempt,
                            "last_error": None,
                        }
                    )
                )
            else:
                error = outcome.error or "The durable effect budget is exhausted."
                terminal_failure = terminal_failure or outcome.dead_lettered
                call_status = "retryable_failed" if outcome.retryable else "terminal_failed"
                if action.tool_call_id:
                    self._update_tool_call(
                        ticket.id,
                        action.tool_call_id,
                        status=call_status,
                        attempts=attempt,
                        error=error,
                    )
                    self._event(
                        ticket.id,
                        "tool.result",
                        json.dumps(
                            {
                                "call_id": action.tool_call_id,
                                "tool_name": action.tool_name,
                                "status": call_status,
                                "attempt": attempt,
                                "error": error,
                                "classification": (
                                    outcome.classification.value
                                    if outcome.classification
                                    else None
                                ),
                                "durable_state": outcome.state.value,
                            },
                            sort_keys=True,
                        ),
                        now,
                    )
                completed.append(
                    action.model_copy(
                        update={
                            "status": "failed",
                            "attempts": attempt,
                            "last_error": error,
                        }
                    )
                )
        resolved = all(action.status == "completed" for action in completed)
        # The provider owns the budget: it flips an action to dead_letter on a
        # non-retryable failure or when attempt_count reaches max_attempts.
        exhausted = terminal_failure
        new_status = "resolved" if resolved else "dead_letter" if exhausted else "action_failed"
        self.connection.execute(
            """
            UPDATE tickets
            SET status = ?, actions_json = ?, approved_at = COALESCE(approved_at, ?)
            WHERE id = ?
            """,
            (
                new_status,
                json.dumps([action.model_dump() for action in completed]),
                now,
                ticket_id,
            ),
        )
        self.connection.commit()
        self._event(
            ticket_id,
            (
                "actions.completed"
                if resolved
                else "actions.dead_lettered"
                if exhausted
                else "actions.failed"
            ),
            "All approved actions completed."
            if resolved
            else "The retry budget is exhausted; operator intervention is required."
            if exhausted
            else "One or more approved actions require retry.",
            now,
        )
        return self.get(ticket_id)

    def _execute_action(
        self,
        ticket: Ticket,
        action: Action,
        now: str,
    ) -> dict[str, Any]:
        """Fire the approved effect exactly once.

        Idempotency, attempt receipts, and dead-lettering are enforced by the
        provider around this call, so it no longer consults a local receipt
        table before acting.
        """

        if action.tool_name:
            result_payload = self.registry.execute(
                ToolContext(
                    connection=self.connection,
                    settings=self.settings,
                    ticket=ticket,
                    now=now,
                    call_id=action.tool_call_id or action.id,
                ),
                ToolCall(
                    id=action.tool_call_id or action.id,
                    name=action.tool_name,
                    arguments=action.arguments,
                ),
            )
            result = str(
                result_payload.get("message") or json.dumps(result_payload, sort_keys=True)
            )
        elif action.kind == "billing_hold":
            self.connection.execute(
                "INSERT OR REPLACE INTO billing_holds VALUES (?, ?, ?, ?)",
                (ticket.id, ticket.company, 7, now),
            )
            result = "Seven-day hold recorded"
            result_payload = {"message": result}
        elif action.kind == "case_update":
            self.connection.execute(
                "INSERT INTO case_events (ticket_id, event, created_at) VALUES (?, ?, ?)",
                (ticket.id, f"{action.label} completed after approval", now),
            )
            result = "Case event recorded"
            result_payload = {"message": result}
        else:
            payload = {"ticket_id": ticket.id, "company": ticket.company, "route": ticket.route}
            delivery_status = "queued"
            if self.settings.notification_webhook_url:
                response = httpx.post(
                    self.settings.notification_webhook_url,
                    json=payload,
                    timeout=10,
                )
                response.raise_for_status()
                delivery_status = "delivered"
            self.connection.execute(
                """
                INSERT INTO notification_outbox
                (ticket_id, payload_json, delivery_status, created_at) VALUES (?, ?, ?, ?)
                """,
                (ticket.id, json.dumps(payload), delivery_status, now),
            )
            result = f"Notification {delivery_status}"
            result_payload = {"message": result, "delivery_status": delivery_status}
        result_payload.setdefault("message", result)
        return result_payload

    @staticmethod
    def _legacy_action_for_call(
        call: ToolCall,
        actions: list[Action],
        consumed_ids: set[str],
    ) -> Action | None:
        expected_kind = {
            "apply_billing_hold": "billing_hold",
            "update_case": "case_update",
            "send_notification": "notification",
        }.get(call.name)
        if not expected_kind:
            return None
        return next(
            (
                action
                for action in actions
                if action.kind == expected_kind and action.id not in consumed_ids
            ),
            None,
        )

    @staticmethod
    def _audit_detail(call: ToolCall, **extra: object) -> str:
        arguments_json = json.dumps(call.arguments, sort_keys=True, separators=(",", ":"))
        detail: dict[str, object] = {
            "call_id": call.id,
            "tool_name": call.name,
            "argument_bytes": len(arguments_json.encode("utf-8")),
            "arguments": call.arguments if len(arguments_json) <= 512 else None,
        }
        if len(arguments_json) > 512:
            detail["arguments_preview"] = arguments_json[:512]
        detail.update(extra)
        return json.dumps(detail, sort_keys=True, default=str)

    def _insert_tool_call(
        self,
        ticket_id: str,
        sequence: int,
        call: ToolCall,
        risk_class: str,
        externally_visible: bool,
        status: str,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO tool_calls
            (id, ticket_id, sequence, tool_name, arguments_json, risk_class,
             externally_visible, status, attempts, result_json, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, NULL)
            """,
            (
                call.id,
                ticket_id,
                sequence,
                call.name,
                json.dumps(call.arguments, sort_keys=True),
                risk_class,
                int(externally_visible),
                status,
            ),
        )
        self.connection.commit()

    def _update_tool_call(
        self,
        ticket_id: str,
        call_id: str,
        *,
        status: str,
        attempts: int | None = None,
        result: dict[str, object] | None = None,
        error: str | None = None,
    ) -> None:
        self.connection.execute(
            """
            UPDATE tool_calls
            SET status = ?,
                attempts = COALESCE(?, attempts),
                result_json = COALESCE(?, result_json),
                error = ?
            WHERE ticket_id = ? AND id = ?
            """,
            (
                status,
                attempts,
                json.dumps(result, sort_keys=True) if result is not None else None,
                error,
                ticket_id,
                call_id,
            ),
        )
        self.connection.commit()

    def tool_calls(self, ticket_id: str) -> list[ToolCallRecord]:
        self.get(ticket_id)
        rows = self.connection.execute(
            "SELECT * FROM tool_calls WHERE ticket_id = ? ORDER BY sequence",
            (ticket_id,),
        ).fetchall()
        return [
            ToolCallRecord(
                id=row["id"],
                ticket_id=row["ticket_id"],
                sequence=row["sequence"],
                tool_name=row["tool_name"],
                arguments=json.loads(row["arguments_json"]),
                risk_class=row["risk_class"],
                externally_visible=bool(row["externally_visible"]),
                status=row["status"],
                attempts=row["attempts"],
                result=json.loads(row["result_json"]) if row["result_json"] else None,
                error=row["error"],
            )
            for row in rows
        ]

    def reject(self, ticket_id: str, note: str) -> Ticket:
        ticket = self.get(ticket_id)
        if ticket.status == "resolved":
            raise ValueError("A resolved ticket cannot be rejected.")
        now = datetime.now(UTC).isoformat()
        self.connection.execute(
            "UPDATE tickets SET status = 'rejected' WHERE id = ?",
            (ticket_id,),
        )
        self.connection.commit()
        self._event(ticket_id, "approval.rejected", note or "Rejected by reviewer.", now)
        return self.get(ticket_id)

    def events(self, ticket_id: str) -> list[WorkflowEvent]:
        self.get(ticket_id)
        rows = self.connection.execute(
            "SELECT * FROM workflow_events WHERE ticket_id = ? ORDER BY id",
            (ticket_id,),
        ).fetchall()
        return [
            WorkflowEvent(
                id=row["id"],
                ticket_id=row["ticket_id"],
                event_type=row["event_type"],
                detail=row["detail"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def _event(self, ticket_id: str, event_type: str, detail: str, created_at: str) -> None:
        self.connection.execute(
            """
            INSERT INTO workflow_events (ticket_id, event_type, detail, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (ticket_id, event_type, detail, created_at),
        )
        self.connection.commit()

    def stats(self, provider: str) -> Stats:
        row = self.connection.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(status = 'needs_approval') AS needs_approval,
                   SUM(status = 'resolved') AS resolved
            FROM tickets
            """
        ).fetchone()
        return Stats(
            tickets=int(row["total"] or 0),
            needs_approval=int(row["needs_approval"] or 0),
            resolved=int(row["resolved"] or 0),
            automation_provider=provider,
        )

    @staticmethod
    def _to_ticket(row: sqlite3.Row) -> Ticket:
        raw = dict(row)
        return Ticket(
            id=raw["id"],
            subject=raw["subject"],
            body=raw["body"],
            customer_name=raw["customer_name"],
            company=raw["company"],
            arr_usd=raw["arr_usd"],
            active_users=raw["active_users"],
            intent=raw["intent"],
            priority=raw["priority"],
            sentiment=raw["sentiment"],
            route=raw["route"],
            confidence=raw["confidence"],
            risk_reason=raw["risk_reason"],
            draft=raw["draft"],
            status=raw["status"],
            sources=[Source.model_validate(item) for item in json.loads(raw["sources_json"])],
            actions=[Action.model_validate(item) for item in json.loads(raw["actions_json"])],
            created_at=datetime.fromisoformat(raw["created_at"]),
            approved_at=(
                datetime.fromisoformat(raw["approved_at"]) if raw["approved_at"] else None
            ),
        )
