from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_prefix="SUPPORT_",
        extra="ignore",
    )

    data_dir: Path = PROJECT_ROOT / "data" / "runtime"
    automation_provider: Literal["local", "openai-compatible"] = "local"
    agent_provider: Literal["deterministic", "openai-compatible"] = "deterministic"
    deployment_mode: Literal["development", "production", "test"] = "development"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    approval_arr_threshold: int = 25_000
    max_action_attempts: int = Field(default=3, ge=1, le=10)
    max_tool_steps: int = Field(default=8, ge=1, le=20)
    max_tool_argument_bytes: int = Field(default=4096, ge=256, le=65_536)
    notification_webhook_url: str = ""
    outbound_allowed_hosts: str = ""
    outbound_allow_private_networks: bool = False
    outbound_connect_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    outbound_read_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    outbound_idempotency_header: str = Field(
        default="Idempotency-Key",
        pattern=r"^[A-Za-z0-9-]{1,64}$",
    )
    outbound_secret_ref: str = Field(default="", max_length=200)
    outbound_secret_header: str = Field(
        default="Authorization",
        pattern=r"^[A-Za-z0-9-]{1,64}$",
    )
    outbound_request_redacted_fields: str = "customer_name,token,secret,authorization"
    outbound_response_redacted_fields: str = "token,secret,authorization"
    mcp_host: str = "127.0.0.1"
    mcp_port: int = Field(default=8001, ge=1, le=65535)
    mcp_http_path: str = Field(default="/mcp", pattern=r"^/[A-Za-z0-9/_-]*$")
    mcp_allow_network: bool = False
    mcp_allowed_hosts: str = ""
    mcp_allowed_origins: str = ""
    mcp_auth_mode: Literal["none", "static-bearer"] = "none"
    mcp_auth_token_ref: str = Field(default="", max_length=200)
    mcp_issuer_url: str = "https://identity.example"
    mcp_resource_server_url: str = "http://127.0.0.1:8001/mcp"
    mcp_required_scopes: str = "relay:tools"
    mcp_max_request_body_bytes: int = Field(default=1_048_576, ge=1024, le=4_194_304)

    @model_validator(mode="after")
    def reject_demo_providers_in_production(self) -> Settings:
        if self.deployment_mode == "production":
            demo_providers = []
            if self.automation_provider == "local":
                demo_providers.append("SUPPORT_AUTOMATION_PROVIDER=local")
            if self.agent_provider == "deterministic":
                demo_providers.append("SUPPORT_AGENT_PROVIDER=deterministic")
            if demo_providers:
                raise ValueError(
                    "Production mode requires explicit non-demo providers; rejected "
                    + ", ".join(demo_providers)
                )
        if self.notification_webhook_url and not self.allowed_outbound_hosts:
            raise ValueError(
                "SUPPORT_OUTBOUND_ALLOWED_HOSTS is required when a notification webhook is set."
            )
        loopback_hosts = {"127.0.0.1", "localhost", "::1"}
        if self.mcp_host not in loopback_hosts and not self.mcp_allow_network:
            raise ValueError(
                "Non-loopback MCP binding requires SUPPORT_MCP_ALLOW_NETWORK=true."
            )
        if self.mcp_allow_network:
            if self.mcp_auth_mode == "none":
                raise ValueError("Network MCP binding requires bearer authentication.")
            if not self.allowed_mcp_hosts:
                raise ValueError(
                    "Network MCP binding requires SUPPORT_MCP_ALLOWED_HOSTS."
                )
        if self.mcp_auth_mode == "static-bearer":
            if not self.mcp_auth_token_ref.startswith("env:"):
                raise ValueError(
                    "Static MCP bearer auth requires an env:NAME token reference."
                )
            if not self.mcp_issuer_url or not self.mcp_resource_server_url:
                raise ValueError("MCP issuer and resource-server URLs are required for auth.")
        return self

    @property
    def allowed_outbound_hosts(self) -> set[str]:
        return {
            item.strip().casefold().rstrip(".")
            for item in self.outbound_allowed_hosts.split(",")
            if item.strip()
        }

    @property
    def request_redacted_fields(self) -> set[str]:
        return {
            item.strip().casefold()
            for item in self.outbound_request_redacted_fields.split(",")
            if item.strip()
        }

    @property
    def response_redacted_fields(self) -> set[str]:
        return {
            item.strip().casefold()
            for item in self.outbound_response_redacted_fields.split(",")
            if item.strip()
        }

    @property
    def allowed_mcp_hosts(self) -> list[str]:
        return [item.strip() for item in self.mcp_allowed_hosts.split(",") if item.strip()]

    @property
    def allowed_mcp_origins(self) -> list[str]:
        return [item.strip() for item in self.mcp_allowed_origins.split(",") if item.strip()]

    @property
    def required_mcp_scopes(self) -> list[str]:
        return [item.strip() for item in self.mcp_required_scopes.split(",") if item.strip()]

    @property
    def sqlite_path(self) -> Path:
        return self.data_dir / "support.sqlite3"
