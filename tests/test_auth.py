"""Tests for pete_mcp_core.auth."""

from __future__ import annotations

import logging

import pytest
from pydantic import SecretStr

from pete_mcp_core.auth import AuthRequiredError, build_auth_provider


class TestBuildAuthProvider:
    def test_returns_none_when_token_missing(self) -> None:
        assert build_auth_provider(None, client_id="test") is None
        assert build_auth_provider("", client_id="test") is None
        assert build_auth_provider("   ", client_id="test") is None

    def test_raises_when_required_and_missing(self) -> None:
        with pytest.raises(AuthRequiredError, match="test"):
            build_auth_provider(None, client_id="test", required=True)
        with pytest.raises(AuthRequiredError):
            build_auth_provider("", client_id="test", required=True)

    def test_builds_verifier_with_raw_string(self) -> None:
        verifier = build_auth_provider("mytoken", client_id="client1")
        assert verifier is not None
        assert hasattr(verifier, "verify_token")

    def test_builds_verifier_with_secret_str(self) -> None:
        verifier = build_auth_provider(SecretStr("mytoken"), client_id="client1")
        assert verifier is not None

    def test_verifier_holds_token_and_client_id(self) -> None:
        verifier = build_auth_provider("mytoken", client_id="client1")
        assert verifier is not None
        # StaticTokenVerifier exposes .tokens as a dict.
        assert "mytoken" in verifier.tokens
        assert verifier.tokens["mytoken"]["client_id"] == "client1"
        assert verifier.tokens["mytoken"]["scopes"] == []

    def test_scopes_passed_through(self) -> None:
        verifier = build_auth_provider("mytoken", client_id="client1", scopes=["read", "write"])
        assert verifier is not None
        assert verifier.tokens["mytoken"]["scopes"] == ["read", "write"]

    def test_token_whitespace_stripped(self) -> None:
        verifier = build_auth_provider("  mytoken  ", client_id="client1")
        assert verifier is not None
        assert "mytoken" in verifier.tokens

    def test_logger_warns_when_no_token(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = logging.getLogger("test.auth")
        with caplog.at_level(logging.WARNING, logger="test.auth"):
            result = build_auth_provider(None, client_id="test", logger=logger)
        assert result is None
        assert any("bearer token" in rec.getMessage().lower() for rec in caplog.records)

    def test_no_warn_when_token_present(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = logging.getLogger("test.auth")
        with caplog.at_level(logging.WARNING, logger="test.auth"):
            build_auth_provider("tok", client_id="test", logger=logger)
        assert not any("bearer token" in rec.getMessage().lower() for rec in caplog.records)

    def test_logger_info_when_auth_enabled(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = logging.getLogger("test.auth")
        with caplog.at_level(logging.INFO, logger="test.auth"):
            result = build_auth_provider("tok", client_id="my-client", logger=logger)
        assert result is not None
        assert any(
            "bearer-token authentication enabled" in rec.getMessage().lower()
            and "my-client" in rec.getMessage()
            for rec in caplog.records
        )

    def test_no_info_when_logger_missing(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO):
            result = build_auth_provider("tok", client_id="test")
        assert result is not None
        assert not any(
            "bearer-token authentication enabled" in rec.getMessage().lower()
            for rec in caplog.records
        )
