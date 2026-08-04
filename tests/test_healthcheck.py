"""Tests for pete_mcp_core.healthcheck."""

from __future__ import annotations

import io
import urllib.error
from unittest.mock import patch

import pytest

from pete_mcp_core.healthcheck import DEFAULT_HEALTHY_CODES, check, main


class _FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return b""


class TestCheck:
    @pytest.mark.parametrize("status", sorted(DEFAULT_HEALTHY_CODES))
    def test_returns_zero_for_healthy_status(self, status: int) -> None:
        with patch("urllib.request.urlopen", return_value=_FakeResponse(status)):
            assert check(8080) == 0

    def test_returns_one_for_unhealthy_status(self) -> None:
        with patch("urllib.request.urlopen", return_value=_FakeResponse(500)):
            assert check(8080) == 1

    def test_returns_zero_for_healthy_http_error(self) -> None:
        exc = urllib.error.HTTPError("u", 405, "m", {}, io.BytesIO(b""))  # type: ignore[arg-type]
        with patch("urllib.request.urlopen", side_effect=exc):
            assert check(8080) == 0

    def test_returns_one_for_unhealthy_http_error(self) -> None:
        exc = urllib.error.HTTPError("u", 500, "m", {}, io.BytesIO(b""))  # type: ignore[arg-type]
        with patch("urllib.request.urlopen", side_effect=exc):
            assert check(8080) == 1

    def test_returns_one_for_connection_refused(self) -> None:
        with patch("urllib.request.urlopen", side_effect=ConnectionRefusedError):
            assert check(8080) == 1

    def test_returns_one_for_url_error(self) -> None:
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("nope")):
            assert check(8080) == 1

    def test_custom_healthy_codes(self) -> None:
        with patch("urllib.request.urlopen", return_value=_FakeResponse(204)):
            assert check(8080, healthy_codes={204}) == 0
            assert check(8080, healthy_codes={200}) == 1

    def test_custom_path_in_url(self) -> None:
        captured: dict[str, str] = {}

        def _capture(url: str, timeout: float) -> _FakeResponse:
            captured["url"] = url
            return _FakeResponse(200)

        with patch("urllib.request.urlopen", side_effect=_capture):
            check(8080, path="/health")
        assert captured["url"] == "http://localhost:8080/health"


class TestMain:
    def test_uses_mcp_port_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_PORT", "3702")
        monkeypatch.delenv("FASTMCP_PORT", raising=False)
        with (
            patch("pete_mcp_core.healthcheck.check", return_value=0) as mock_check,
            pytest.raises(SystemExit) as exc,
        ):
            main()
        assert exc.value.code == 0
        mock_check.assert_called_once_with(3702, path="/mcp")

    def test_uses_fastmcp_port_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MCP_PORT", raising=False)
        monkeypatch.setenv("FASTMCP_PORT", "3703")
        with (
            patch("pete_mcp_core.healthcheck.check", return_value=0) as mock_check,
            pytest.raises(SystemExit),
        ):
            main()
        mock_check.assert_called_once_with(3703, path="/mcp")

    def test_default_port_when_env_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MCP_PORT", raising=False)
        monkeypatch.delenv("FASTMCP_PORT", raising=False)
        with (
            patch("pete_mcp_core.healthcheck.check", return_value=1) as mock_check,
            pytest.raises(SystemExit) as exc,
        ):
            main()
        assert exc.value.code == 1
        mock_check.assert_called_once_with(3800, path="/mcp")

    def test_custom_health_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_PORT", "3800")
        monkeypatch.setenv("MCP_HEALTH_PATH", "/health")
        with (
            patch("pete_mcp_core.healthcheck.check", return_value=0) as mock_check,
            pytest.raises(SystemExit),
        ):
            main()
        mock_check.assert_called_once_with(3800, path="/health")

    def test_invalid_port_exits_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_PORT", "not-a-number")
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1
