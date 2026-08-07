"""Approve a ticket in a separate OS process so it can be killed mid-effect.

Phase 6 fault case 3 requires a worker that dies *after* the target applied the
effect but *before* the receipt is durable. Simulating that in-process cannot
prove the recovery path, because a Python-level exception still unwinds
normally. This module is launched as a real subprocess and killed with a
signal, leaving the provider's `delivery_actions` row stranded in `running`
exactly as an abrupt crash would.

Usage: python -m tests.crash_worker <data_dir> <ticket_id> <webhook_url>
"""

from __future__ import annotations

import sys
from pathlib import Path

from support_desk.config import Settings
from support_desk.store import TicketStore


def main(argv: list[str]) -> int:
    data_dir, ticket_id, webhook_url = argv[1], argv[2], argv[3]
    settings = Settings(
        data_dir=Path(data_dir),
        automation_provider="local",
        notification_webhook_url=webhook_url,
        outbound_allowed_hosts="127.0.0.1",
        outbound_allow_private_networks=True,
        outbound_read_timeout_seconds=60,
        outbound_connect_timeout_seconds=10,
    )
    store = TicketStore(settings)
    try:
        # Expected never to return: the target hangs after applying, and the
        # parent kills this process while the request is in flight.
        store.approve(ticket_id)
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
