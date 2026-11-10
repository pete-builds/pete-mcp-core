"""Tests for pete_mcp_core.session_reaper.

Nothing in this file asserts what the installed SDK or FastMCP defaults to.
Four tests once did (an unpatched manager "has no timeout"), the SDK changed
its default from None to 1800, and ``main`` went red with no change to this
repo. The reaper's job is to make the timeout independent of that default, so
the behavior tests run in three worlds: a stand-in SDK that defaults to None
and rejects a stateless timeout, a stand-in that defaults to 1800 and accepts
one, and whatever SDK is really installed.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from typing import Any

import fastmcp
import pytest
from fastmcp import FastMCP
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from pydantic import BaseModel

from pete_mcp_core import session_reaper
from pete_mcp_core.session_reaper import (
    DEFAULT_IDLE_TIMEOUT,
    _fastmcp_none_is_unset,
    _resolve_timeout,
    enable_session_reaper,
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MCP_SESSION_IDLE_TIMEOUT", raising=False)


def _sdk_init(default: float | None, *, rejects_stateless_timeout: bool) -> Callable[..., None]:
    """A stand-in for the SDK manager's ``__init__`` with a chosen default.

    Same parameter order as the real one, so positional calls bind the same way.
    """

    def __init__(
        self: Any,
        app: Any,
        event_store: Any = None,
        json_response: bool = False,
        stateless: bool = False,
        security_settings: Any = None,
        retry_interval: int | None = None,
        session_idle_timeout: float | None = default,
    ) -> None:
        if rejects_stateless_timeout and stateless and session_idle_timeout is not None:
            raise RuntimeError("session_idle_timeout is not supported in stateless mode")
        self.stateless = stateless
        self.session_idle_timeout = session_idle_timeout

    return __init__


@pytest.fixture(params=["sdk-default-none", "sdk-default-1800", "sdk-installed"])
def sdk(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    """Run a test against each SDK default the reaper has to cope with."""
    if request.param == "sdk-default-none":
        # Measured on mcp 1.27.0 and 2.1.0.
        init = _sdk_init(None, rejects_stateless_timeout=True)
        monkeypatch.setattr(StreamableHTTPSessionManager, "__init__", init)
    elif request.param == "sdk-default-1800":
        # Measured on mcp 1.30.0 and 2.3.0.
        init = _sdk_init(1800, rejects_stateless_timeout=False)
        monkeypatch.setattr(StreamableHTTPSessionManager, "__init__", init)
    return str(request.param)


class _FastMCPBuilt(StreamableHTTPSessionManager):
    """Builds the manager the way FastMCP 4 does: the timeout is always passed."""

    __module__ = "fastmcp.server.http"

    def __init__(
        self, app: Any, stateless: bool = False, session_idle_timeout: float | None = None
    ) -> None:
        super().__init__(app=app, stateless=stateless, session_idle_timeout=session_idle_timeout)


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
    """Every test here holds whatever the SDK defaults to (the ``sdk`` fixture)."""

    def test_injects_default_timeout(self, sdk: str) -> None:
        assert enable_session_reaper() == DEFAULT_IDLE_TIMEOUT
        manager = StreamableHTTPSessionManager(app=object())
        assert manager.session_idle_timeout == DEFAULT_IDLE_TIMEOUT

    def test_reads_env(self, sdk: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_SESSION_IDLE_TIMEOUT", "900")
        assert enable_session_reaper() == 900.0
        manager = StreamableHTTPSessionManager(app=object())
        assert manager.session_idle_timeout == 900.0

    def test_explicit_timeout_wins(self, sdk: str) -> None:
        enable_session_reaper(60.0)
        manager = StreamableHTTPSessionManager(app=object())
        assert manager.session_idle_timeout == 60.0

    def test_never_overrides_an_explicit_caller(self, sdk: str) -> None:
        enable_session_reaper()
        manager = StreamableHTTPSessionManager(app=object(), session_idle_timeout=30.0)
        assert manager.session_idle_timeout == 30.0

    def test_never_overrides_a_caller_who_chose_none(self, sdk: str) -> None:
        enable_session_reaper()
        manager = StreamableHTTPSessionManager(app=object(), session_idle_timeout=None)
        assert manager.session_idle_timeout is None

    @pytest.mark.parametrize("value", ["off", "0"])
    def test_disabled_means_no_timeout(
        self, sdk: str, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        """``off`` has to beat an SDK that would default to 1800 on its own."""
        monkeypatch.setenv("MCP_SESSION_IDLE_TIMEOUT", value)
        assert enable_session_reaper() is None
        manager = StreamableHTTPSessionManager(app=object())
        assert manager.session_idle_timeout is None

    def test_non_positive_argument_means_no_timeout(self, sdk: str) -> None:
        assert enable_session_reaper(0.0) is None
        manager = StreamableHTTPSessionManager(app=object())
        assert manager.session_idle_timeout is None

    def test_leaves_stateless_mode_alone(self, sdk: str) -> None:
        """An older SDK raises if a stateless manager is handed an idle timeout."""
        untouched = StreamableHTTPSessionManager(app=object(), stateless=True)
        enable_session_reaper(60.0)
        manager = StreamableHTTPSessionManager(app=object(), stateless=True)
        assert manager.session_idle_timeout == untouched.session_idle_timeout

    def test_leaves_stateless_passed_positionally_alone(self, sdk: str) -> None:
        untouched = StreamableHTTPSessionManager(object(), None, False, True)
        enable_session_reaper(60.0)
        manager = StreamableHTTPSessionManager(object(), None, False, True)
        assert manager.session_idle_timeout == untouched.session_idle_timeout

    def test_first_call_decides(self, sdk: str) -> None:
        """``run_server`` calls this with no argument after a server's own call."""
        assert enable_session_reaper(120.0) == 120.0
        first = StreamableHTTPSessionManager.__init__
        assert enable_session_reaper(999.0) == 120.0
        assert enable_session_reaper() == 120.0
        assert StreamableHTTPSessionManager.__init__ is first
        manager = StreamableHTTPSessionManager(app=object())
        assert manager.session_idle_timeout == 120.0

    def test_first_call_decides_when_it_disabled(self, sdk: str) -> None:
        assert enable_session_reaper(0.0) is None
        assert enable_session_reaper(999.0) is None
        manager = StreamableHTTPSessionManager(app=object())
        assert manager.session_idle_timeout is None

    def test_logs_the_installed_timeout(self, sdk: str, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO, logger="pete_mcp_core.session_reaper"):
            enable_session_reaper(300.0)
        assert any("Session idle reaper enabled at 300s" in r.getMessage() for r in caplog.records)

    def test_logs_when_disabled(self, sdk: str, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO, logger="pete_mcp_core.session_reaper"):
            enable_session_reaper(0.0)
        assert any("Session idle timeout disabled" in r.getMessage() for r in caplog.records)


class TestFastMCPPassingNone:
    """FastMCP 4.0.x always passes its setting, and the setting defaults to None."""

    @pytest.fixture
    def none_is_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(session_reaper, "_fastmcp_none_is_unset", lambda: True)

    @pytest.fixture
    def none_is_a_choice(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(session_reaper, "_fastmcp_none_is_unset", lambda: False)

    def test_default_none_gets_the_timeout(self, sdk: str, none_is_unset: None) -> None:
        enable_session_reaper()
        manager = _FastMCPBuilt(object())
        assert manager.session_idle_timeout == DEFAULT_IDLE_TIMEOUT

    def test_a_number_from_fastmcp_still_wins(self, sdk: str, none_is_unset: None) -> None:
        enable_session_reaper()
        manager = _FastMCPBuilt(object(), session_idle_timeout=600.0)
        assert manager.session_idle_timeout == 600.0

    def test_disabled_stays_none(self, sdk: str, none_is_unset: None) -> None:
        enable_session_reaper(0.0)
        manager = _FastMCPBuilt(object())
        assert manager.session_idle_timeout is None

    def test_stateless_is_left_alone(self, sdk: str, none_is_unset: None) -> None:
        enable_session_reaper()
        manager = _FastMCPBuilt(object(), stateless=True)
        assert manager.session_idle_timeout is None

    def test_none_from_any_other_caller_is_a_choice(self, sdk: str, none_is_unset: None) -> None:
        enable_session_reaper()
        manager = StreamableHTTPSessionManager(app=object(), session_idle_timeout=None)
        assert manager.session_idle_timeout is None

    def test_none_is_a_choice_once_fastmcp_defaults_to_auto(
        self, sdk: str, none_is_a_choice: None
    ) -> None:
        enable_session_reaper()
        manager = _FastMCPBuilt(object())
        assert manager.session_idle_timeout is None


class TestFastMCPNoneIsUnset:
    def test_true_when_the_setting_defaults_to_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class Settings(BaseModel):
            http_session_idle_timeout: float | None = None

        monkeypatch.setattr(fastmcp, "settings", Settings())
        assert _fastmcp_none_is_unset() is True

    def test_false_when_the_setting_defaults_to_auto(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class Settings(BaseModel):
            http_session_idle_timeout: float | str | None = "auto"

        monkeypatch.setattr(fastmcp, "settings", Settings())
        assert _fastmcp_none_is_unset() is False

    def test_false_when_fastmcp_has_no_such_setting(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class Settings(BaseModel):
            pass

        monkeypatch.setattr(fastmcp, "settings", Settings())
        assert _fastmcp_none_is_unset() is False


class TestOldSdk:
    def test_installed_sdk_supports_the_parameter(self) -> None:
        """Positive control: if this fails the reaper is moot, not broken."""
        params = inspect.signature(StreamableHTTPSessionManager.__init__).parameters
        assert "session_idle_timeout" in params

    @staticmethod
    def _legacy_init(self: Any, app: Any, event_store: Any = None, stateless: bool = False) -> None:
        self.session_idle_timeout = None

    def test_warns_when_sdk_lacks_support(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr(StreamableHTTPSessionManager, "__init__", self._legacy_init)
        with caplog.at_level(logging.WARNING, logger="pete_mcp_core.session_reaper"):
            assert enable_session_reaper() is None
        assert any("does not accept session_idle_timeout" in r.getMessage() for r in caplog.records)
        assert StreamableHTTPSessionManager.__init__ is self._legacy_init

    def test_no_warning_when_disabled_anyway(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr(StreamableHTTPSessionManager, "__init__", self._legacy_init)
        with caplog.at_level(logging.WARNING, logger="pete_mcp_core.session_reaper"):
            assert enable_session_reaper(0.0) is None
        assert caplog.records == []


class TestLiveFastMCPApp:
    """What a real ``FastMCP().http_app()`` hands the installed SDK.

    The stand-ins above pin the logic; these pin the outcome on the FastMCP and
    SDK pair actually installed, which is the pair CI varies.
    """

    @staticmethod
    async def _live_manager(
        monkeypatch: pytest.MonkeyPatch, **http_kwargs: Any
    ) -> StreamableHTTPSessionManager:
        created: list[StreamableHTTPSessionManager] = []
        init = StreamableHTTPSessionManager.__init__

        def recording(self: StreamableHTTPSessionManager, *args: Any, **kwargs: Any) -> None:
            init(self, *args, **kwargs)
            created.append(self)

        monkeypatch.setattr(StreamableHTTPSessionManager, "__init__", recording)
        app = FastMCP("reaper-live").http_app(transport="streamable-http", **http_kwargs)
        async with app.router.lifespan_context(app):
            pass
        assert len(created) == 1
        return created[0]

    async def test_default_timeout_reaches_the_live_manager(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        enable_session_reaper()
        manager = await self._live_manager(monkeypatch)
        assert manager.session_idle_timeout == DEFAULT_IDLE_TIMEOUT

    async def test_env_timeout_reaches_the_live_manager(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MCP_SESSION_IDLE_TIMEOUT", "900")
        enable_session_reaper()
        manager = await self._live_manager(monkeypatch)
        assert manager.session_idle_timeout == 900.0

    async def test_disabled_reaches_the_live_manager(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_SESSION_IDLE_TIMEOUT", "off")
        enable_session_reaper()
        manager = await self._live_manager(monkeypatch)
        assert manager.session_idle_timeout is None

    async def test_stateless_app_still_starts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        enable_session_reaper(60.0)
        manager = await self._live_manager(monkeypatch, stateless_http=True)
        assert manager.stateless is True
        assert manager.session_idle_timeout != 60.0

    async def test_fastmcp_own_setting_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        if not hasattr(fastmcp.settings, "http_session_idle_timeout"):
            pytest.skip("this FastMCP has no http_session_idle_timeout setting")
        fastmcp.settings.http_session_idle_timeout = 600.0
        enable_session_reaper()
        manager = await self._live_manager(monkeypatch)
        assert manager.session_idle_timeout == 600.0

    async def test_fastmcp_setting_of_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A choice where FastMCP defaults to "auto", the absence of one on 4.0.x."""
        if not hasattr(fastmcp.settings, "http_session_idle_timeout"):
            pytest.skip("this FastMCP has no http_session_idle_timeout setting")
        fastmcp.settings.http_session_idle_timeout = None
        expected = DEFAULT_IDLE_TIMEOUT if _fastmcp_none_is_unset() else None
        enable_session_reaper()
        manager = await self._live_manager(monkeypatch)
        assert manager.session_idle_timeout == expected
