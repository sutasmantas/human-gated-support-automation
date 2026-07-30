from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime

import httpx

from support_desk.config import Settings
from support_desk.engine import AutomationResult
from support_desk.schemas import Action, Source, Stats, Ticket, TicketCreate, WorkflowEvent


class TicketStore:
    def __init__(self, settings: Settings) -> None:
        settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings = settings
        self.connection = sqlite3.connect(settings.sqlite_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
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
            CREATE TABLE IF NOT EXISTS action_receipts (
                ticket_id TEXT NOT NULL,
                action_id TEXT NOT NULL,
                result TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (ticket_id, action_id)
            );
            CREATE TABLE IF NOT EXISTS action_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id TEXT NOT NULL,
                action_id TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                status TEXT NOT NULL,
                error TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS workflow_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                detail TEXT NOT NULL,
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
                json.dumps([action.model_dump() for action in result.actions]),
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
                "Human reviewer approved the proposed reply and side effects.",
                now,
            )
        completed: list[Action] = []
        for action in ticket.actions:
            if action.status == "completed":
                completed.append(action)
                continue
            attempt = action.attempts + 1
            try:
                result = self._execute_action(ticket, action, now)
                self._record_attempt(ticket.id, action.id, attempt, "completed", None, now)
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
            except httpx.HTTPError as exc:
                error = f"{type(exc).__name__}: {exc}"
                self._record_attempt(ticket.id, action.id, attempt, "failed", error, now)
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
        exhausted = any(
            action.status == "failed"
            and action.attempts >= self.settings.max_action_attempts
            for action in completed
        )
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

    def _execute_action(self, ticket: Ticket, action: Action, now: str) -> str:
        receipt = self.connection.execute(
            "SELECT result FROM action_receipts WHERE ticket_id = ? AND action_id = ?",
            (ticket.id, action.id),
        ).fetchone()
        if receipt:
            return str(receipt["result"])
        if action.kind == "billing_hold":
            self.connection.execute(
                "INSERT OR REPLACE INTO billing_holds VALUES (?, ?, ?, ?)",
                (ticket.id, ticket.company, 7, now),
            )
            result = "Seven-day hold recorded"
        elif action.kind == "case_update":
            self.connection.execute(
                "INSERT INTO case_events (ticket_id, event, created_at) VALUES (?, ?, ?)",
                (ticket.id, f"{action.label} completed after approval", now),
            )
            result = "Case event recorded"
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
        self.connection.execute(
            "INSERT OR IGNORE INTO action_receipts VALUES (?, ?, ?, ?)",
            (ticket.id, action.id, result, now),
        )
        return result

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

    def _record_attempt(
        self,
        ticket_id: str,
        action_id: str,
        attempt: int,
        status: str,
        error: str | None,
        created_at: str,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO action_attempts
            (ticket_id, action_id, attempt, status, error, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (ticket_id, action_id, attempt, status, error, created_at),
        )

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
