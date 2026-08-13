"""Tests for pete_mcp_core.session_reaper."""

from __future__ import annotations

import logging

import pytest
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from pete_mcp_core.session_reaper import (
    DEFAULT_IDLE_TIMEOUT,
    _resolve_timeout,
    enable_session_reaper,
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MCP_SESSION_IDLE_TIMEOUT", raising=False)


class TestResolveTimeout:
    def test_defaults_when_env_missing(self) -> None:
        assert _resolve_timeout(None) == DEFAULT_IDLE_TIMEOUT

    def test_explicit_wins_over_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_SESSION_IDLE_TIMEOUT", "900")
        assert _resolve_timeout(60.0) == 60.0

    def test_reads_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_SESSION_IDLE_TIMEOUT", "900")
        assert _resolve_timeout(None) == 900.0

    @pytest.mark.parametrize("value", ["off", "0", "none", "false", "DISABLED"])
    def test_disable_values(self, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        monkeypatch.setenv("MCP_SESSION_IDLE_TIMEOUT", value)
        assert _resolve_timeout(None) is None

    def test_blank_env_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_SESSION_IDLE_TIMEOUT", "   ")
        assert _resolve_timeout(None) == DEFAULT_IDLE_TIMEOUT

    def test_rejects_garbage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_SESSION_IDLE_TIMEOUT", "half an hour")
        with pytest.raises(ValueError, match="MCP_SESSION_IDLE_TIMEOUT"):
            _resolve_timeout(None)

    def test_negative_explicit_disables(self) -> None:
        assert _resolve_timeout(-1.0) is None


class TestEnableSessionReaper:
    def test_sdk_supports_the_parameter(self) -> None:
        """Positive control: if this fails the workaround is moot, not broken."""
        import inspect

        params = inspect.signature(StreamableHTTPSessionManager.__init__).parameters
        assert "session_idle_timeout" in params

    def test_injects_default_timeout(self) -> None:
        enable_session_reaper()
        manager = StreamableHTTPSessionManager(app=object())
        assert manager.session_idle_timeout == DEFAULT_IDLE_TIMEOUT

    def test_unpatched_manager_has_no_timeout(self) -> None:
        """Negative control: without the patch the SDK default really is None."""
        manager = StreamableHTTPSessionManager(app=object())
        assert manager.session_idle_timeout is None

    def test_explicit_timeout_wins(self) -> None:
        enable_session_reaper(60.0)
        manager = StreamableHTTPSessionManager(app=object())
        assert manager.session_idle_timeout == 60.0

    def test_never_overrides_an_explicit_caller(self) -> None:
        enable_session_reaper()
        manager = StreamableHTTPSessionManager(app=object(), session_idle_timeout=30.0)
        assert manager.session_idle_timeout == 30.0

    def test_skips_stateless_mode(self) -> None:
        """The SDK raises if a stateless manager is handed an idle timeout."""
        enable_session_reaper()
        manager = StreamableHTTPSessionManager(app=object(), stateless=True)
        assert manager.session_idle_timeout is None

    def test_skips_stateless_passed_positionally(self) -> None:
        enable_session_reaper()
        manager = StreamableHTTPSessionManager(object(), None, False, True)
        assert manager.session_idle_timeout is None

    def test_disabled_leaves_sdk_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_SESSION_IDLE_TIMEOUT", "off")
        assert enable_session_reaper() is None
        manager = StreamableHTTPSessionManager(app=object())
        assert manager.session_idle_timeout is None

    def test_is_idempotent(self) -> None:
        enable_session_reaper(120.0)
        first = StreamableHTTPSessionManager.__init__
        assert enable_session_reaper(999.0) == 999.0
        assert StreamableHTTPSessionManager.__init__ is first
        manager = StreamableHTTPSessionManager(app=object())
        assert manager.session_idle_timeout == 120.0

    def test_logs_the_installed_timeout(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO, logger="pete_mcp_core.session_reaper"):
            enable_session_reaper(300.0)
        assert any("Session idle reaper enabled" in r.getMessage() for r in caplog.records)

    def test_warns_when_sdk_lacks_support(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        def legacy_init(self, app, event_store=None, json_response=False, stateless=False):
            self.session_idle_timeout = None

        monkeypatch.setattr(StreamableHTTPSessionManager, "__init__", legacy_init)
        with caplog.at_level(logging.WARNING, logger="pete_mcp_core.session_reaper"):
            assert enable_session_reaper() is None
        assert any("does not accept session_idle_timeout" in r.getMessage() for r in caplog.records)
