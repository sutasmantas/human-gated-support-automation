from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime

import httpx

from support_desk.config import Settings
from support_desk.engine import AutomationResult
from support_desk.schemas import Action, Source, Stats, Ticket, TicketCreate


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
        now = datetime.now(UTC).isoformat()
        completed: list[Action] = []
        for action in ticket.actions:
            result = self._execute_action(ticket, action, now)
            completed.append(action.model_copy(update={"status": "completed", "result": result}))
        self.connection.execute(
            """
            UPDATE tickets
            SET status = 'resolved', actions_json = ?, approved_at = ?
            WHERE id = ?
            """,
            (json.dumps([action.model_dump() for action in completed]), now, ticket_id),
        )
        self.connection.commit()
        return self.get(ticket_id)

    def _execute_action(self, ticket: Ticket, action: Action, now: str) -> str:
        if action.kind == "billing_hold":
            self.connection.execute(
                "INSERT OR REPLACE INTO billing_holds VALUES (?, ?, ?, ?)",
                (ticket.id, ticket.company, 7, now),
            )
            return "Seven-day hold recorded"
        if action.kind == "case_update":
            self.connection.execute(
                "INSERT INTO case_events (ticket_id, event, created_at) VALUES (?, ?, ?)",
                (ticket.id, "Renewal case updated after approval", now),
            )
            return "Case event recorded"

        payload = {"ticket_id": ticket.id, "company": ticket.company, "route": ticket.route}
        delivery_status = "queued"
        if self.settings.notification_webhook_url:
            try:
                response = httpx.post(
                    self.settings.notification_webhook_url,
                    json=payload,
                    timeout=10,
                )
                response.raise_for_status()
                delivery_status = "delivered"
            except httpx.HTTPError:
                delivery_status = "failed"
        self.connection.execute(
            """
            INSERT INTO notification_outbox
            (ticket_id, payload_json, delivery_status, created_at) VALUES (?, ?, ?, ?)
            """,
            (ticket.id, json.dumps(payload), delivery_status, now),
        )
        return f"Notification {delivery_status}"

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
