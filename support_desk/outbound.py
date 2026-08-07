from __future__ import annotations

import ipaddress
import os
import socket
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

# REDACTED is re-exported deliberately: tests and callers import it from this
# module, which is the adapter's public surface for outbound evidence.
from deliveryguard.redaction import (
    REDACTED,  # noqa: F401  (public re-export)
    redact,
)
from pydantic import BaseModel

from support_desk.config import Settings

Resolver = Callable[..., list[tuple[Any, ...]]]
METADATA_HOSTS = {
    "metadata",
    "metadata.google.internal",
    "instance-data",
}
METADATA_ADDRESSES = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("169.254.170.2"),
    ipaddress.ip_address("100.100.100.200"),
}


class OutboundRetryableError(RuntimeError):
    def __init__(self, classification: str, message: str) -> None:
        self.classification = classification
        super().__init__(f"{classification}: {message}")


class OutboundTerminalError(RuntimeError):
    def __init__(self, classification: str, message: str) -> None:
        self.classification = classification
        super().__init__(f"{classification}: {message}")


class OutboundResult(BaseModel):
    status: str
    classification: str
    http_status: int
    destination: str
    idempotency_header: str
    idempotency_key: str
    request: dict[str, Any]
    response: dict[str, Any]


class OutboundDescription(BaseModel):
    adapter: str
    destination: str | None
    allowed_hosts: list[str]
    allow_private_networks: bool
    connect_timeout_seconds: float
    read_timeout_seconds: float
    idempotency_header: str
    secret_ref: str | None
    request_redacted_fields: list[str]
    response_redacted_fields: list[str]


class EnvironmentSecretResolver:
    def resolve(self, reference: str) -> str:
        if not reference.startswith("env:"):
            raise OutboundTerminalError(
                "invalid_secret_reference",
                "Only env:NAME secret references are supported.",
            )
        variable = reference.removeprefix("env:")
        if not variable or not variable.replace("_", "").isalnum():
            raise OutboundTerminalError(
                "invalid_secret_reference",
                "Secret environment variable name is invalid.",
            )
        value = os.environ.get(variable)
        if not value:
            raise OutboundTerminalError(
                "missing_secret",
                f"Secret reference env:{variable} is not available.",
            )
        return value


class OutboundHTTPAdapter:
    name = "generic-rest-webhook"

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        resolver: Resolver = socket.getaddrinfo,
        secret_resolver: EnvironmentSecretResolver | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport
        self.resolver = resolver
        self.secret_resolver = secret_resolver or EnvironmentSecretResolver()

    def describe(self) -> OutboundDescription:
        destination = None
        if self.settings.notification_webhook_url:
            destination = self._safe_destination(self.settings.notification_webhook_url)
        return OutboundDescription(
            adapter=self.name,
            destination=destination,
            allowed_hosts=sorted(self.settings.allowed_outbound_hosts),
            allow_private_networks=self.settings.outbound_allow_private_networks,
            connect_timeout_seconds=self.settings.outbound_connect_timeout_seconds,
            read_timeout_seconds=self.settings.outbound_read_timeout_seconds,
            idempotency_header=self.settings.outbound_idempotency_header,
            secret_ref=self.settings.outbound_secret_ref or None,
            request_redacted_fields=sorted(self.settings.request_redacted_fields),
            response_redacted_fields=sorted(self.settings.response_redacted_fields),
        )

    def send(
        self,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> OutboundResult:
        url = self.settings.notification_webhook_url
        if not url:
            raise OutboundTerminalError("missing_destination", "No outbound URL is configured.")
        destination = self.validate_destination(url)
        headers = {
            "Content-Type": "application/json",
            self.settings.outbound_idempotency_header: idempotency_key,
        }
        if self.settings.outbound_secret_ref:
            secret = self.secret_resolver.resolve(self.settings.outbound_secret_ref)
            headers[self.settings.outbound_secret_header] = f"Bearer {secret}"

        timeout = httpx.Timeout(
            connect=self.settings.outbound_connect_timeout_seconds,
            read=self.settings.outbound_read_timeout_seconds,
            write=self.settings.outbound_read_timeout_seconds,
            pool=self.settings.outbound_connect_timeout_seconds,
        )
        try:
            with httpx.Client(
                timeout=timeout,
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
            ) as client:
                response = client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise OutboundRetryableError("timeout", "Outbound request timed out.") from exc
        except httpx.NetworkError as exc:
            raise OutboundRetryableError(
                "network_error", "Outbound destination was unreachable."
            ) from exc

        safe_request = redact(payload, frozenset(self.settings.request_redacted_fields))
        if response.status_code == 409:
            safe_response = self._response_payload(response, allow_empty=True)
            return OutboundResult(
                status="already_applied",
                classification="conflict_already_applied",
                http_status=response.status_code,
                destination=destination,
                idempotency_header=self.settings.outbound_idempotency_header,
                idempotency_key=idempotency_key,
                request=safe_request,
                response=redact(
                    safe_response,
                    frozenset(self.settings.response_redacted_fields),
                ),
            )
        if response.status_code == 429:
            raise OutboundRetryableError("rate_limit", "Outbound target returned HTTP 429.")
        if response.status_code >= 500:
            raise OutboundRetryableError(
                "server_error", f"Outbound target returned HTTP {response.status_code}."
            )
        if 300 <= response.status_code < 400:
            raise OutboundTerminalError(
                "redirect_rejected", "Outbound redirects are not followed."
            )
        if response.status_code >= 400:
            raise OutboundTerminalError(
                "client_error", f"Outbound target returned HTTP {response.status_code}."
            )

        safe_response = self._response_payload(response, allow_empty=response.status_code == 204)
        return OutboundResult(
            status="delivered",
            classification="success",
            http_status=response.status_code,
            destination=destination,
            idempotency_header=self.settings.outbound_idempotency_header,
            idempotency_key=idempotency_key,
            request=safe_request,
            response=redact(safe_response, frozenset(self.settings.response_redacted_fields)),
        )

    def validate_destination(self, url: str) -> str:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"}:
            raise OutboundTerminalError(
                "invalid_destination", "Only HTTP and HTTPS destinations are supported."
            )
        if parsed.username or parsed.password:
            raise OutboundTerminalError(
                "invalid_destination", "Embedded destination credentials are forbidden."
            )
        host = (parsed.hostname or "").casefold().rstrip(".")
        if not host:
            raise OutboundTerminalError("invalid_destination", "Destination host is missing.")
        if host not in self.settings.allowed_outbound_hosts:
            raise OutboundTerminalError(
                "destination_not_allowlisted", f"Destination host {host!r} is not allowlisted."
            )
        if host in METADATA_HOSTS:
            raise OutboundTerminalError(
                "unsafe_destination", "Cloud metadata destinations are forbidden."
            )
        try:
            addresses = {
                ipaddress.ip_address(item[4][0])
                for item in self.resolver(host, parsed.port or 443, type=socket.SOCK_STREAM)
            }
        except (OSError, ValueError) as exc:
            raise OutboundTerminalError(
                "destination_resolution_failed", "Destination host could not be resolved."
            ) from exc
        if not addresses:
            raise OutboundTerminalError(
                "destination_resolution_failed", "Destination host resolved to no addresses."
            )
        for address in addresses:
            if address in METADATA_ADDRESSES or address.is_link_local:
                raise OutboundTerminalError(
                    "unsafe_destination", "Link-local and metadata addresses are forbidden."
                )
            if address.is_multicast or address.is_reserved or address.is_unspecified:
                raise OutboundTerminalError(
                    "unsafe_destination", "Non-routable destination is forbidden."
                )
            private = address.is_private or address.is_loopback
            if private and not self.settings.outbound_allow_private_networks:
                raise OutboundTerminalError(
                    "unsafe_destination", "Private or non-public destination is forbidden."
                )
        return self._safe_destination(url)

    @staticmethod
    def _safe_destination(url: str) -> str:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        try:
            port = parsed.port
        except ValueError:
            port = None
        authority = f"{host}:{port}" if port else host
        return urlunsplit((parsed.scheme, authority, parsed.path, "", ""))

    @staticmethod
    def _response_payload(response: httpx.Response, *, allow_empty: bool) -> dict[str, Any]:
        if allow_empty and not response.content:
            return {}
        try:
            payload = response.json()
        except ValueError as exc:
            raise OutboundTerminalError(
                "malformed_response", "Outbound target did not return valid JSON."
            ) from exc
        if not isinstance(payload, dict):
            raise OutboundTerminalError(
                "malformed_response", "Outbound JSON response must be an object."
            )
        return payload

