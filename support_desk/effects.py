"""Durable effect execution delegated to the DeliveryGuard provider.

Relay used to hand-roll idempotency, attempt history, and dead-lettering across
the ``action_receipts`` and ``action_attempts`` tables. Those responsibilities
now belong to ``deliveryguard.store.DeliveryStore``; this module is the only
seam between Relay's approval workflow and the provider.

Relay composes the provider at the **store** level rather than through
``DeliveryExecutor``. Relay's retry cadence is human-paced: every attempt is a
separate operator action against ``POST /api/tickets/{id}/retry``, and
``max_action_attempts`` bounds how many times a reviewer may re-fire an
externally visible effect. ``DeliveryExecutor`` binds attempts per call, so it
cannot express that budget without collapsing the operator loop. The provider
still enforces the bound — ``record_failure`` flips to ``dead_letter`` at
``attempt_count >= max_attempts`` and ``start_attempt`` refuses to run past it —
Relay only chooses when each attempt happens.

The outbound transport stays Relay's own ``OutboundHTTPAdapter``, which carries
the host allowlist and metadata-address blocking that the provider's generic
``WebhookAdapter`` does not have.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from deliveryguard.identifiers import make_idempotency_key
from deliveryguard.models import (
    ActionState,
    Classification,
    DeliveryFailure,
    DeliveryResult,
)
from deliveryguard.store import DeliveryStateError, DeliveryStore

from support_desk.tools import ToolRetryableError, ToolTerminalError

IDEMPOTENCY_NAMESPACE = "relay"

TERMINAL_STATES = frozenset(
    {ActionState.DELIVERED, ActionState.ALREADY_APPLIED, ActionState.DEAD_LETTER}
)

SUCCESS_STATES = frozenset({ActionState.DELIVERED, ActionState.ALREADY_APPLIED})

#: Relay's transport-level classification strings mapped onto the provider's
#: vocabulary. Anything unmapped falls back by retryability so an unrecognised
#: classification can never silently become a success.
CLASSIFICATION_BY_NAME: dict[str, Classification] = {
    "timeout": Classification.NETWORK_ERROR,
    "network_error": Classification.NETWORK_ERROR,
    "rate_limit": Classification.RATE_LIMIT,
    "server_error": Classification.SERVER_ERROR,
    "client_error": Classification.CLIENT_ERROR,
    "redirect_rejected": Classification.CLIENT_ERROR,
    "malformed_response": Classification.MALFORMED_RESPONSE,
    "missing_destination": Classification.CONFIGURATION_ERROR,
    "invalid_destination": Classification.CONFIGURATION_ERROR,
    "destination_not_allowlisted": Classification.CONFIGURATION_ERROR,
    "destination_resolution_failed": Classification.CONFIGURATION_ERROR,
    "unsafe_destination": Classification.CONFIGURATION_ERROR,
    "invalid_secret_reference": Classification.CONFIGURATION_ERROR,
    "missing_secret": Classification.CONFIGURATION_ERROR,
    "secret_resolution_error": Classification.CONFIGURATION_ERROR,
}


def classify(name: str | None, *, retryable: bool) -> Classification:
    if name and name in CLASSIFICATION_BY_NAME:
        return CLASSIFICATION_BY_NAME[name]
    return Classification.SERVER_ERROR if retryable else Classification.CLIENT_ERROR


def effect_idempotency_key(
    *,
    ticket_id: str,
    action_id: str,
    tool_name: str | None,
    arguments: Mapping[str, Any],
) -> str:
    """Derive the durable key that binds one approved action to one effect.

    The key is stable across operator retries and bound to the arguments, so a
    mutated payload is rejected by the provider as an idempotency conflict
    rather than silently firing a different effect under the same identity.
    """

    return make_idempotency_key(
        IDEMPOTENCY_NAMESPACE,
        {
            "ticket_id": ticket_id,
            "action_id": action_id,
            "tool_name": tool_name,
            "arguments": dict(arguments),
        },
    )


@dataclass(frozen=True)
class EffectOutcome:
    """What one operator-paced attempt did, as recorded by the provider."""

    state: ActionState
    attempt_count: int
    cycle: int
    result: dict[str, Any] | None
    classification: Classification | None
    error: str | None
    executed: bool
    """False when the provider returned a terminal record without re-firing."""
    retryable: bool | None = None
    """Retryability of the last failure, independent of budget exhaustion."""

    @property
    def succeeded(self) -> bool:
        return self.state in SUCCESS_STATES

    @property
    def dead_lettered(self) -> bool:
        return self.state is ActionState.DEAD_LETTER


def default_success_classification(result: Mapping[str, Any]) -> Classification:
    if result.get("delivery_status") == "already_applied":
        return Classification.ALREADY_APPLIED
    return Classification.SUCCESS


class DurableEffectGateway:
    """Runs one attempt of an approved effect under provider-owned durability."""

    def __init__(
        self,
        store: DeliveryStore,
        *,
        max_attempts: int,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.store = store
        self.max_attempts = max_attempts
        self._clock = clock

    def execute(
        self,
        *,
        idempotency_key: str,
        destination: str,
        payload: Mapping[str, Any],
        correlation_id: str,
        effect: Callable[[], dict[str, Any]],
        classify_success: Callable[
            [Mapping[str, Any]], Classification
        ] = default_success_classification,
    ) -> EffectOutcome:
        action, _created = self.store.register(
            idempotency_key=idempotency_key,
            destination=destination,
            payload=payload,
            correlation_id=correlation_id,
            max_attempts=self.max_attempts,
        )

        if action.state is ActionState.RUNNING:
            # A previous worker died between starting the attempt and writing
            # its receipt. The provider records an explicit interrupted receipt
            # instead of assuming either outcome.
            action = self.store.recover_interrupted(action.id)

        if action.state in TERMINAL_STATES:
            return self._replayed(action)

        try:
            running = self.store.start_attempt(action.id)
        except DeliveryStateError:
            # The budget was already spent; surface the durable record instead
            # of firing an unbounded effect.
            return self._replayed(self.store.get(action.id))

        started = self._clock()
        try:
            result = effect()
        except ToolRetryableError as exc:
            return self._failed(running.id, exc, retryable=True, started=started)
        except ToolTerminalError as exc:
            return self._failed(running.id, exc, retryable=False, started=started)
        except Exception as exc:
            # Mirror the provider's own executor: an unnormalized exception is
            # a non-retryable failure with a receipt, never a stranded running
            # row that a later attempt would silently re-fire.
            normalized = ToolTerminalError(
                f"Effect raised unnormalized {type(exc).__name__}: {exc}",
                classification="malformed_response",
            )
            return self._failed(running.id, normalized, retryable=False, started=started)

        classification = classify_success(result)
        response = result.get("adapter") or {}
        record = self.store.record_success(
            running.id,
            DeliveryResult(
                classification,
                http_status=_http_status(response),
                response=response if isinstance(response, dict) else {},
            ),
            latency_ms=(self._clock() - started) * 1000,
        )
        return EffectOutcome(
            state=record.state,
            attempt_count=record.attempt_count,
            cycle=record.cycle,
            result=result,
            classification=classification,
            error=None,
            executed=True,
        )

    def replay(self, idempotency_key: str, *, correlation_id: str) -> None:
        """Return a dead-lettered action to the pending pool for a new cycle."""

        action = self.store.get_by_key(idempotency_key)
        self.store.replay(action.id, correlation_id=correlation_id)

    def attempts(self, idempotency_key: str) -> list[Any]:
        action = self.store.get_by_key(idempotency_key)
        return self.store.attempts(action.id)

    def _failed(
        self,
        action_id: str,
        exc: ToolRetryableError | ToolTerminalError,
        *,
        retryable: bool,
        started: float,
    ) -> EffectOutcome:
        classification = classify(getattr(exc, "classification", None), retryable=retryable)
        record = self.store.record_failure(
            action_id,
            DeliveryFailure(classification, str(exc), retryable=retryable),
            latency_ms=(self._clock() - started) * 1000,
        )
        return EffectOutcome(
            state=record.state,
            attempt_count=record.attempt_count,
            cycle=record.cycle,
            result=None,
            classification=classification,
            error=f"{type(exc).__name__}: {exc}",
            executed=True,
            retryable=retryable,
        )

    @staticmethod
    def _replayed(action: Any) -> EffectOutcome:
        return EffectOutcome(
            state=action.state,
            attempt_count=action.attempt_count,
            cycle=action.cycle,
            result=None,
            classification=action.last_classification,
            error=action.last_error,
            executed=False,
        )


def _http_status(response: Any) -> int | None:
    if isinstance(response, dict):
        status = response.get("http_status")
        if isinstance(status, int):
            return status
    return None
