"""Tests for pete_mcp_core.settings."""

from __future__ import annotations

import pytest
from pydantic import Field, ValidationError

from pete_mcp_core.settings import BaseCoreSettings


class TestBaseCoreSettings:
    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for var in [
            "MCP_TRANSPORT",
            "MCP_HOST",
            "FASTMCP_HOST",
            "MCP_PORT",
            "FASTMCP_PORT",
            "MCP_LOG_LEVEL",
            "MCP_LOG_FORMAT",
            "MCP_AUTH_TOKEN",
            "MCP_AUTH_REQUIRED",
        ]:
            monkeypatch.delenv(var, raising=False)

        settings = BaseCoreSettings(_env_file=None)
        assert settings.transport == "stdio"
        assert settings.host == "0.0.0.0"
        assert settings.port == 3800
        assert settings.log_level == "INFO"
        assert settings.log_format == "json"
        assert settings.auth_token is None
        assert settings.auth_required is False

    def test_env_vars_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
        monkeypatch.setenv("MCP_HOST", "127.0.0.1")
        monkeypatch.setenv("MCP_PORT", "3801")
        monkeypatch.setenv("MCP_LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("MCP_LOG_FORMAT", "text")
        monkeypatch.setenv("MCP_AUTH_TOKEN", "s3cret")
        monkeypatch.setenv("MCP_AUTH_REQUIRED", "true")

        settings = BaseCoreSettings(_env_file=None)
        assert settings.transport == "streamable-http"
        assert settings.host == "127.0.0.1"
        assert settings.port == 3801
        assert settings.log_level == "DEBUG"
        assert settings.log_format == "text"
        assert settings.auth_token is not None
        assert settings.auth_token.get_secret_value() == "s3cret"
        assert settings.auth_required is True

    def test_fastmcp_host_alias(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MCP_HOST", raising=False)
        monkeypatch.setenv("FASTMCP_HOST", "192.168.1.1")
        settings = BaseCoreSettings(_env_file=None)
        assert settings.host == "192.168.1.1"

    def test_fastmcp_port_alias(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MCP_PORT", raising=False)
        monkeypatch.setenv("FASTMCP_PORT", "3900")
        settings = BaseCoreSettings(_env_file=None)
        assert settings.port == 3900

    def test_invalid_transport_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_TRANSPORT", "carrier-pigeon")
        with pytest.raises(ValidationError):
            BaseCoreSettings(_env_file=None)

    def test_invalid_log_format_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_LOG_FORMAT", "yaml")
        with pytest.raises(ValidationError):
            BaseCoreSettings(_env_file=None)

    def test_subclass_can_add_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_SPOTIFY_CLIENT_ID", "abc123")

        class SpotifySettings(BaseCoreSettings):
            spotify_client_id: str = Field(default="")

        settings = SpotifySettings(_env_file=None)
        assert settings.spotify_client_id == "abc123"
        assert settings.transport == "stdio"

    def test_extra_env_vars_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_TOTALLY_UNKNOWN_KEY", "whatever")
        settings = BaseCoreSettings(_env_file=None)
        assert settings.transport == "stdio"

    def test_auth_token_is_secret_str(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_AUTH_TOKEN", "topsecret")
        settings = BaseCoreSettings(_env_file=None)
        assert "topsecret" not in repr(settings.auth_token)
        assert "topsecret" not in str(settings.auth_token)
