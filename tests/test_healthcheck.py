"""Tests for pete_mcp_core.healthcheck."""

from __future__ import annotations

import io
import urllib.error
from email.message import Message
from unittest.mock import patch

import pytest

from pete_mcp_core.healthcheck import (
    DEFAULT_HEALTH_PATH,
    DEFAULT_HEALTHY_CODES,
    TRANSPORT_PATHS,
    _resolve_healthy_codes,
    check,
    main,
)


def _headers(**pairs: str) -> Message:
    msg = Message()
    for key, value in pairs.items():
        msg[key.replace("_", "-")] = value
    return msg


class _FakeResponse:
    def __init__(self, status: int, headers: Message | None = None) -> None:
        self.status = status
        self.headers = headers if headers is not None else Message()
        self.closed = False

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return b""

    def close(self) -> None:
        self.closed = True


def _http_error(code: int, headers: Message | None = None) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "u", code, "m", headers if headers is not None else Message(), io.BytesIO(b"")
    )


class TestDefaults:
    def test_default_path_is_not_a_transport_path(self) -> None:
        # The whole point of the fix: the default probe must not land on the
        # streamable-http mount, where every request creates a leaked session.
        assert DEFAULT_HEALTH_PATH not in TRANSPORT_PATHS
        assert DEFAULT_HEALTH_PATH.startswith("/")

    def test_default_codes_superset_of_legacy(self) -> None:
        # Backward compatibility: nothing that passed before may fail now.
        assert {200, 400, 405, 406} <= DEFAULT_HEALTHY_CODES

    def test_sentinel_404_is_healthy(self) -> None:
        assert 404 in DEFAULT_HEALTHY_CODES

    def test_credential_and_auth_codes_are_healthy(self) -> None:
        # A restart cannot renew a credential or supply a bearer token, so
        # neither may fail the container healthcheck.
        assert 401 in DEFAULT_HEALTHY_CODES
        assert 503 in DEFAULT_HEALTHY_CODES

    def test_server_error_is_not_healthy(self) -> None:
        assert 500 not in DEFAULT_HEALTHY_CODES


class TestCheck:
    @pytest.mark.parametrize("status", sorted(DEFAULT_HEALTHY_CODES))
    def test_returns_zero_for_healthy_status(self, status: int) -> None:
        with patch("urllib.request.urlopen", return_value=_FakeResponse(status)):
            assert check(8080) == 0

    def test_returns_one_for_unhealthy_status(self) -> None:
        with patch("urllib.request.urlopen", return_value=_FakeResponse(500)):
            assert check(8080) == 1

    def test_returns_zero_for_healthy_http_error(self) -> None:
        with patch("urllib.request.urlopen", side_effect=_http_error(405)):
            assert check(8080) == 0

    def test_returns_one_for_unhealthy_http_error(self) -> None:
        with patch("urllib.request.urlopen", side_effect=_http_error(500)):
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

    def test_default_url_uses_sentinel_path(self) -> None:
        captured: dict[str, str] = {}

        def _capture(url: str, timeout: float) -> _FakeResponse:
            captured["url"] = url
            return _FakeResponse(404)

        with patch("urllib.request.urlopen", side_effect=_capture):
            assert check(8080) == 0
        assert captured["url"] == f"http://localhost:8080{DEFAULT_HEALTH_PATH}"

    def test_custom_path_in_url(self) -> None:
        captured: dict[str, str] = {}

        def _capture(url: str, timeout: float) -> _FakeResponse:
            captured["url"] = url
            return _FakeResponse(200)

        with patch("urllib.request.urlopen", side_effect=_capture):
            check(8080, path="/health")
        assert captured["url"] == "http://localhost:8080/health"

    def test_custom_host_in_url(self) -> None:
        captured: dict[str, str] = {}

        def _capture(url: str, timeout: float) -> _FakeResponse:
            captured["url"] = url
            return _FakeResponse(200)

        with patch("urllib.request.urlopen", side_effect=_capture):
            check(8080, path="/health", host="127.0.0.1")
        assert captured["url"] == "http://127.0.0.1:8080/health"

    def test_uses_a_plain_get_no_request_object(self) -> None:
        # HEAD and OPTIONS were measured to create a transport session exactly
        # like GET, so the method is not the fix and must not silently change.
        captured: list[object] = []

        def _capture(url: object, timeout: float) -> _FakeResponse:
            captured.append(url)
            return _FakeResponse(404)

        with patch("urllib.request.urlopen", side_effect=_capture):
            check(8080)
        assert captured == [f"http://localhost:8080{DEFAULT_HEALTH_PATH}"]


class TestTransportPathWarning:
    @pytest.mark.parametrize("path", sorted(TRANSPORT_PATHS))
    def test_warns_when_probing_a_transport_path(
        self, path: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch("urllib.request.urlopen", return_value=_FakeResponse(406)):
            assert check(8080, path=path) == 0
        assert "leaks a transport session" in capsys.readouterr().err

    def test_no_warning_on_default_path(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("urllib.request.urlopen", return_value=_FakeResponse(404)):
            check(8080)
        assert capsys.readouterr().err == ""


class TestSessionReaping:
    def test_reaps_session_when_response_carries_session_id(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        calls: list[tuple[str, str | None]] = []

        def _capture(target: object, timeout: float) -> _FakeResponse:
            if isinstance(target, urllib.request.Request):
                calls.append((target.get_method(), target.headers.get("Mcp-session-id")))
                return _FakeResponse(200)
            calls.append(("GET", None))
            return _FakeResponse(406, _headers(mcp_session_id="abc123"))

        with patch("urllib.request.urlopen", side_effect=_capture):
            assert check(8080, path="/mcp") == 0

        assert calls == [("GET", None), ("DELETE", "abc123")]
        assert "reaping it" in capsys.readouterr().err

    def test_reaps_session_from_http_error_response(self) -> None:
        # The real /mcp probe returns 406, which urllib raises as HTTPError,
        # so the session id arrives on the exception rather than a response.
        with patch("urllib.request.urlopen") as mock:
            mock.side_effect = [
                _http_error(406, _headers(mcp_session_id="from-error")),
                _FakeResponse(200),
            ]
            assert check(8080, path="/mcp") == 0
        assert mock.call_count == 2
        reap_request = mock.call_args.args[0]
        assert reap_request.get_method() == "DELETE"
        assert reap_request.headers.get("Mcp-session-id") == "from-error"

    def test_no_reap_when_no_session_header(self) -> None:
        with patch("urllib.request.urlopen", return_value=_FakeResponse(404)) as mock:
            assert check(8080) == 0
        assert mock.call_count == 1

    def test_reap_failure_does_not_change_health_verdict(self) -> None:
        def _capture(target: object, timeout: float) -> _FakeResponse:
            if isinstance(target, urllib.request.Request):
                raise ConnectionResetError("reap failed")
            return _FakeResponse(406, _headers(mcp_session_id="abc123"))

        with patch("urllib.request.urlopen", side_effect=_capture):
            assert check(8080, path="/mcp") == 0

    def test_reap_http_error_does_not_change_health_verdict(self) -> None:
        def _capture(target: object, timeout: float) -> _FakeResponse:
            if isinstance(target, urllib.request.Request):
                raise _http_error(404)
            return _FakeResponse(406, _headers(mcp_session_id="abc123"))

        with patch("urllib.request.urlopen", side_effect=_capture):
            assert check(8080, path="/mcp") == 0

    def test_unhealthy_status_still_unhealthy_after_reap(self) -> None:
        def _capture(target: object, timeout: float) -> _FakeResponse:
            if isinstance(target, urllib.request.Request):
                return _FakeResponse(200)
            return _FakeResponse(500, _headers(mcp_session_id="abc123"))

        with patch("urllib.request.urlopen", side_effect=_capture):
            assert check(8080, path="/mcp") == 1


class TestResolveHealthyCodes:
    def test_none_returns_defaults(self) -> None:
        assert _resolve_healthy_codes(None) is DEFAULT_HEALTHY_CODES

    def test_blank_returns_defaults(self) -> None:
        assert _resolve_healthy_codes("   ") is DEFAULT_HEALTHY_CODES

    def test_parses_comma_separated(self) -> None:
        assert _resolve_healthy_codes("200,503") == frozenset({200, 503})

    def test_tolerates_whitespace_and_empty_entries(self) -> None:
        assert _resolve_healthy_codes(" 200 , , 404 ,") == frozenset({200, 404})

    def test_single_value(self) -> None:
        assert _resolve_healthy_codes("200") == frozenset({200})

    def test_non_integer_falls_back_to_defaults(self, capsys: pytest.CaptureFixture[str]) -> None:
        # A typo must never fail the container: a restart cannot fix an env var.
        assert _resolve_healthy_codes("200,oops") is DEFAULT_HEALTHY_CODES
        assert "non-integer entry" in capsys.readouterr().err

    def test_only_separators_falls_back_to_defaults(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _resolve_healthy_codes(",,,") is DEFAULT_HEALTHY_CODES
        assert "empty set" in capsys.readouterr().err


class TestMain:
    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in ("MCP_PORT", "FASTMCP_PORT", "MCP_HEALTH_PATH", "MCP_HEALTH_CODES"):
            monkeypatch.delenv(name, raising=False)

    def test_uses_mcp_port_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_PORT", "3702")
        with (
            patch("pete_mcp_core.healthcheck.check", return_value=0) as mock_check,
            pytest.raises(SystemExit) as exc,
        ):
            main()
        assert exc.value.code == 0
        mock_check.assert_called_once_with(
            3702, path=DEFAULT_HEALTH_PATH, healthy_codes=DEFAULT_HEALTHY_CODES
        )

    def test_uses_fastmcp_port_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FASTMCP_PORT", "3703")
        with (
            patch("pete_mcp_core.healthcheck.check", return_value=0) as mock_check,
            pytest.raises(SystemExit),
        ):
            main()
        assert mock_check.call_args.args == (3703,)

    def test_fastmcp_port_wins_over_mcp_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Matches serve.py's precedence so the healthcheck never targets a
        # different port than run_server binds.
        monkeypatch.setenv("FASTMCP_PORT", "3703")
        monkeypatch.setenv("MCP_PORT", "9999")
        with (
            patch("pete_mcp_core.healthcheck.check", return_value=0) as mock_check,
            pytest.raises(SystemExit),
        ):
            main()
        assert mock_check.call_args.args == (3703,)

    def test_default_port_when_env_absent(self) -> None:
        with (
            patch("pete_mcp_core.healthcheck.check", return_value=1) as mock_check,
            pytest.raises(SystemExit) as exc,
        ):
            main()
        assert exc.value.code == 1
        assert mock_check.call_args.args == (3800,)

    def test_caller_default_port_when_env_absent(self) -> None:
        with (
            patch("pete_mcp_core.healthcheck.check", return_value=0) as mock_check,
            pytest.raises(SystemExit),
        ):
            main(default_port=3707)
        assert mock_check.call_args.args == (3707,)

    def test_env_still_wins_over_caller_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FASTMCP_PORT", "4242")
        with (
            patch("pete_mcp_core.healthcheck.check", return_value=0) as mock_check,
            pytest.raises(SystemExit),
        ):
            main(default_port=3707)
        assert mock_check.call_args.args == (4242,)

    def test_defaults_to_sentinel_path_not_mcp(self) -> None:
        # The regression this whole change exists to prevent.
        with (
            patch("pete_mcp_core.healthcheck.check", return_value=0) as mock_check,
            pytest.raises(SystemExit),
        ):
            main()
        assert mock_check.call_args.kwargs["path"] == DEFAULT_HEALTH_PATH
        assert mock_check.call_args.kwargs["path"] not in TRANSPORT_PATHS

    def test_custom_health_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_PORT", "3800")
        monkeypatch.setenv("MCP_HEALTH_PATH", "/health")
        with (
            patch("pete_mcp_core.healthcheck.check", return_value=0) as mock_check,
            pytest.raises(SystemExit),
        ):
            main()
        mock_check.assert_called_once_with(
            3800, path="/health", healthy_codes=DEFAULT_HEALTHY_CODES
        )

    def test_legacy_mcp_health_path_still_honored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # ~20 servers may still carry ENV MCP_HEALTH_PATH=/mcp; it must not break.
        monkeypatch.setenv("MCP_HEALTH_PATH", "/mcp")
        with (
            patch("pete_mcp_core.healthcheck.check", return_value=0) as mock_check,
            pytest.raises(SystemExit),
        ):
            main()
        assert mock_check.call_args.kwargs["path"] == "/mcp"

    def test_blank_health_path_falls_back_to_sentinel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MCP_HEALTH_PATH", "")
        with (
            patch("pete_mcp_core.healthcheck.check", return_value=0) as mock_check,
            pytest.raises(SystemExit),
        ):
            main()
        assert mock_check.call_args.kwargs["path"] == DEFAULT_HEALTH_PATH

    def test_health_codes_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_HEALTH_PATH", "/healthz")
        monkeypatch.setenv("MCP_HEALTH_CODES", "200,503")
        with (
            patch("pete_mcp_core.healthcheck.check", return_value=0) as mock_check,
            pytest.raises(SystemExit),
        ):
            main()
        assert mock_check.call_args.kwargs["healthy_codes"] == frozenset({200, 503})

    def test_bad_health_codes_env_does_not_fail_container(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MCP_HEALTH_CODES", "not-a-code")
        with (
            patch("pete_mcp_core.healthcheck.check", return_value=0) as mock_check,
            pytest.raises(SystemExit) as exc,
        ):
            main()
        assert exc.value.code == 0
        assert mock_check.call_args.kwargs["healthy_codes"] is DEFAULT_HEALTHY_CODES

    def test_invalid_port_exits_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_PORT", "not-a-number")
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1

    def test_propagates_unhealthy_exit_code(self) -> None:
        with (
            patch("pete_mcp_core.healthcheck.check", return_value=1),
            pytest.raises(SystemExit) as exc,
        ):
            main()
        assert exc.value.code == 1
