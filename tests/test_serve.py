"""Tests for pete_mcp_core.serve."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from pete_mcp_core.serve import (
    _resolve_host,
    _resolve_port,
    _resolve_transport,
    run_server,
)


class TestResolveTransport:
    def test_defaults_when_env_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MCP_TRANSPORT", raising=False)
        assert _resolve_transport("stdio") == "stdio"

    def test_env_overrides_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
        assert _resolve_transport("stdio") == "streamable-http"

    def test_lowercases_input(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_TRANSPORT", "STDIO")
        assert _resolve_transport("streamable-http") == "stdio"

    def test_rejects_unknown_transport(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_TRANSPORT", "carrier-pigeon")
        with pytest.raises(ValueError, match="MCP_TRANSPORT"):
            _resolve_transport("stdio")

    def test_warns_when_env_overrides_default(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv("MCP_TRANSPORT", "stdio")
        with caplog.at_level(logging.WARNING, logger="pete_mcp_core.serve"):
            assert _resolve_transport("streamable-http") == "stdio"
        assert any(
            "MCP_TRANSPORT env overrode default transport" in rec.getMessage()
            for rec in caplog.records
        )

    def test_no_warn_when_env_matches_default(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
        with caplog.at_level(logging.WARNING, logger="pete_mcp_core.serve"):
            _resolve_transport("streamable-http")
        assert not any("MCP_TRANSPORT env overrode" in rec.getMessage() for rec in caplog.records)

    def test_no_warn_when_env_unset(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.delenv("MCP_TRANSPORT", raising=False)
        with caplog.at_level(logging.WARNING, logger="pete_mcp_core.serve"):
            _resolve_transport("streamable-http")
        assert not any("MCP_TRANSPORT env overrode" in rec.getMessage() for rec in caplog.records)


class TestResolveHost:
    def test_prefers_fastmcp_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FASTMCP_HOST", "10.0.0.1")
        monkeypatch.setenv("MCP_HOST", "10.0.0.2")
        assert _resolve_host("0.0.0.0") == "10.0.0.1"

    def test_falls_back_to_mcp_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FASTMCP_HOST", raising=False)
        monkeypatch.setenv("MCP_HOST", "10.0.0.2")
        assert _resolve_host("0.0.0.0") == "10.0.0.2"

    def test_uses_default_when_both_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FASTMCP_HOST", raising=False)
        monkeypatch.delenv("MCP_HOST", raising=False)
        assert _resolve_host("127.0.0.1") == "127.0.0.1"


class TestResolvePort:
    def test_prefers_fastmcp_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FASTMCP_PORT", "3701")
        monkeypatch.setenv("MCP_PORT", "3702")
        assert _resolve_port(3800) == 3701

    def test_falls_back_to_mcp_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FASTMCP_PORT", raising=False)
        monkeypatch.setenv("MCP_PORT", "3702")
        assert _resolve_port(3800) == 3702

    def test_uses_default_when_both_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FASTMCP_PORT", raising=False)
        monkeypatch.delenv("MCP_PORT", raising=False)
        assert _resolve_port(3800) == 3800

    def test_rejects_non_int(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_PORT", "abc")
        with pytest.raises(ValueError, match="integer"):
            _resolve_port(3800)


class TestRunServer:
    def test_stdio_transport_calls_run_stdio(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_TRANSPORT", "stdio")
        mock_mcp = MagicMock()
        run_server(mock_mcp)
        mock_mcp.run.assert_called_once_with(transport="stdio")

    def test_streamable_http_calls_run_with_host_port(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
        monkeypatch.setenv("MCP_HOST", "1.2.3.4")
        monkeypatch.setenv("MCP_PORT", "9999")
        monkeypatch.delenv("FASTMCP_HOST", raising=False)
        monkeypatch.delenv("FASTMCP_PORT", raising=False)
        mock_mcp = MagicMock()
        run_server(mock_mcp, default_port=3800)
        mock_mcp.run.assert_called_once_with(transport="streamable-http", host="1.2.3.4", port=9999)

    def test_streamable_http_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
        monkeypatch.delenv("MCP_HOST", raising=False)
        monkeypatch.delenv("MCP_PORT", raising=False)
        monkeypatch.delenv("FASTMCP_HOST", raising=False)
        monkeypatch.delenv("FASTMCP_PORT", raising=False)
        mock_mcp = MagicMock()
        run_server(mock_mcp, default_port=3801, default_host="127.0.0.1")
        mock_mcp.run.assert_called_once_with(
            transport="streamable-http", host="127.0.0.1", port=3801
        )

    def test_streamable_http_mirrors_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
        monkeypatch.setenv("MCP_HOST", "1.2.3.4")
        monkeypatch.setenv("MCP_PORT", "9999")
        monkeypatch.delenv("FASTMCP_HOST", raising=False)
        monkeypatch.delenv("FASTMCP_PORT", raising=False)
        mock_mcp = MagicMock()
        run_server(mock_mcp)
        import os

        assert os.environ["FASTMCP_HOST"] == "1.2.3.4"
        assert os.environ["FASTMCP_PORT"] == "9999"

    def test_default_transport_is_stdio(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MCP_TRANSPORT", raising=False)
        mock_mcp = MagicMock()
        run_server(mock_mcp)
        mock_mcp.run.assert_called_once_with(transport="stdio")

    def test_default_transport_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MCP_TRANSPORT", raising=False)
        monkeypatch.delenv("MCP_HOST", raising=False)
        monkeypatch.delenv("MCP_PORT", raising=False)
        monkeypatch.delenv("FASTMCP_HOST", raising=False)
        monkeypatch.delenv("FASTMCP_PORT", raising=False)
        mock_mcp = MagicMock()
        run_server(mock_mcp, default_transport="streamable-http", default_port=3805)
        mock_mcp.run.assert_called_once_with(transport="streamable-http", host="0.0.0.0", port=3805)

    def test_http_startup_banner_logs_host_port(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.delenv("MCP_TRANSPORT", raising=False)
        monkeypatch.delenv("MCP_HOST", raising=False)
        monkeypatch.delenv("MCP_PORT", raising=False)
        monkeypatch.delenv("FASTMCP_HOST", raising=False)
        monkeypatch.delenv("FASTMCP_PORT", raising=False)
        mock_mcp = MagicMock()
        with caplog.at_level(logging.INFO, logger="pete_mcp_core.serve"):
            run_server(
                mock_mcp,
                default_transport="streamable-http",
                default_port=3707,
                default_host="127.0.0.1",
            )
        assert any(
            "127.0.0.1:3707" in rec.getMessage() and "streamable-http" in rec.getMessage()
            for rec in caplog.records
        )

    def test_stdio_startup_banner_logs_stdio(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv("MCP_TRANSPORT", "stdio")
        mock_mcp = MagicMock()
        with caplog.at_level(logging.INFO, logger="pete_mcp_core.serve"):
            run_server(mock_mcp)
        assert any("stdio transport" in rec.getMessage() for rec in caplog.records)
