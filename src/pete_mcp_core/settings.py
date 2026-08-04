"""Pydantic-settings base for MCP servers.

Covers the fields every server was reading independently: transport, host,
port, log level/format, and an optional bearer token. Servers subclass and
add their own domain fields.

Reads from environment (``MCP_*``) and ``.env``. Extra fields are ignored so
subclasses can add domain-specific env vars without needing to redeclare
the base ones.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseCoreSettings(BaseSettings):
    """Base settings for MCP servers. Subclass and add your own fields."""

    model_config = SettingsConfigDict(
        env_prefix="MCP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    transport: Literal["stdio", "streamable-http"] = Field(
        default="stdio",
        description="Transport for FastMCP to serve on.",
    )
    host: str = Field(
        default="0.0.0.0",
        description="Bind host for streamable-http.",
        validation_alias=AliasChoices("MCP_HOST", "FASTMCP_HOST"),
    )
    port: int = Field(
        default=3800,
        description="Bind port for streamable-http.",
        validation_alias=AliasChoices("MCP_PORT", "FASTMCP_PORT"),
    )
    log_level: str = Field(
        default="INFO",
        description="Log level (DEBUG/INFO/WARNING/ERROR/CRITICAL).",
    )
    log_format: Literal["json", "text"] = Field(
        default="json",
        description="Log format.",
    )
    auth_token: SecretStr | None = Field(
        default=None,
        description="Bearer token for the streamable-http transport. Unset = no auth.",
    )
    auth_required: bool = Field(
        default=False,
        description="If True and streamable-http is selected, refuse to start without auth_token.",
    )
