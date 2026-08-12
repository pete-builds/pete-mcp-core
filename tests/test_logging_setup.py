"""Tests for pete_mcp_core.logging_setup."""

from __future__ import annotations

import json
import logging
import sys

import pytest

from pete_mcp_core.logging_setup import (
    DEFAULT_SENSITIVE_KEYS,
    JsonFormatter,
    _scrub,
    configure_logging,
)


class TestScrub:
    def test_scrubs_top_level_sensitive_key(self) -> None:
        result = _scrub({"api_key": "abc", "user": "pete"}, DEFAULT_SENSITIVE_KEYS)
        assert result == {"api_key": "[REDACTED]", "user": "pete"}

    def test_scrubs_nested_sensitive_key(self) -> None:
        result = _scrub(
            {"config": {"password": "hunter2", "port": 22}},
            DEFAULT_SENSITIVE_KEYS,
        )
        assert result == {"config": {"password": "[REDACTED]", "port": 22}}

    def test_scrubs_inside_list(self) -> None:
        result = _scrub(
            [{"token": "t1"}, {"token": "t2"}],
            DEFAULT_SENSITIVE_KEYS,
        )
        assert result == [{"token": "[REDACTED]"}, {"token": "[REDACTED]"}]

    def test_case_insensitive_key_matching(self) -> None:
        result = _scrub({"API_KEY": "x", "X-Api-Key": "y"}, DEFAULT_SENSITIVE_KEYS)
        assert result == {"API_KEY": "[REDACTED]", "X-Api-Key": "[REDACTED]"}

    def test_passes_through_primitives(self) -> None:
        assert _scrub(42, DEFAULT_SENSITIVE_KEYS) == 42
        assert _scrub("hello", DEFAULT_SENSITIVE_KEYS) == "hello"
        assert _scrub(None, DEFAULT_SENSITIVE_KEYS) is None


class TestJsonFormatter:
    def test_produces_valid_json(self) -> None:
        record = logging.LogRecord("test", logging.INFO, "path", 1, "hello %s", ("world",), None)
        formatter = JsonFormatter()
        line = formatter.format(record)
        parsed = json.loads(line)
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test"
        assert parsed["msg"] == "hello world"
        assert "ts" in parsed

    def test_includes_extras(self) -> None:
        record = logging.LogRecord("t", logging.INFO, "p", 1, "m", (), None)
        record.user_id = 42
        record.password = "hunter2"
        line = JsonFormatter().format(record)
        parsed = json.loads(line)
        assert parsed["extra"]["user_id"] == 42
        assert parsed["extra"]["password"] == "[REDACTED]"

    def test_includes_exc_info(self) -> None:
        try:
            raise ValueError("boom")
        except ValueError:
            exc_info = sys.exc_info()
        record = logging.LogRecord("t", logging.ERROR, "p", 1, "m", (), exc_info)
        line = JsonFormatter().format(record)
        parsed = json.loads(line)
        assert "exc_info" in parsed
        assert "ValueError" in parsed["exc_info"]

    def test_respects_custom_sensitive_keys(self) -> None:
        keys = frozenset(DEFAULT_SENSITIVE_KEYS | {"unifi_api_key"})
        formatter = JsonFormatter(sensitive_keys=keys)
        record = logging.LogRecord("t", logging.INFO, "p", 1, "m", (), None)
        record.details = {"unifi_api_key": "leak"}
        parsed = json.loads(formatter.format(record))
        assert parsed["extra"]["details"]["unifi_api_key"] == "[REDACTED]"


def _core_handlers() -> list[logging.Handler]:
    """Return only the handlers configure_logging owns."""
    return [h for h in logging.getLogger().handlers if getattr(h, "_pete_mcp_core_handler", False)]


class TestConfigureLogging:
    def teardown_method(self) -> None:
        # Remove only our handlers; leave pytest's LogCaptureHandler alone so
        # subsequent tests still get log capture.
        root = logging.getLogger()
        for handler in list(root.handlers):
            if getattr(handler, "_pete_mcp_core_handler", False):
                root.removeHandler(handler)

    def test_installs_stderr_handler(self) -> None:
        configure_logging(level="INFO", fmt="json")
        core = _core_handlers()
        assert len(core) == 1
        handler = core[0]
        assert isinstance(handler, logging.StreamHandler)
        assert handler.stream is sys.stderr

    def test_idempotent(self) -> None:
        configure_logging(level="INFO", fmt="json")
        configure_logging(level="DEBUG", fmt="text")
        assert len(_core_handlers()) == 1
        assert logging.getLogger().level == logging.DEBUG

    def test_preserves_external_handlers(self) -> None:
        # A handler installed by something else (pytest's LogCaptureHandler is
        # the load-bearing example) must survive configure_logging so the
        # caller's log capture keeps working after a server module import.
        root = logging.getLogger()
        external = logging.NullHandler()
        root.addHandler(external)
        try:
            configure_logging(level="INFO", fmt="json")
            assert external in root.handlers
            # Second call should also leave the external handler in place
            # while still only owning one core handler.
            configure_logging(level="INFO", fmt="text")
            assert external in root.handlers
            assert len(_core_handlers()) == 1
        finally:
            root.removeHandler(external)

    def test_json_format(self) -> None:
        configure_logging(level="INFO", fmt="json")
        handler = _core_handlers()[0]
        assert isinstance(handler.formatter, JsonFormatter)

    def test_text_format(self) -> None:
        configure_logging(level="INFO", fmt="text")
        handler = _core_handlers()[0]
        assert not isinstance(handler.formatter, JsonFormatter)

    def test_extra_sensitive_keys_extend(self) -> None:
        configure_logging(
            level="INFO",
            fmt="json",
            extra_sensitive_keys=["unifi_api_key", "wlan_passphrase"],
        )
        handler = _core_handlers()[0]
        assert isinstance(handler.formatter, JsonFormatter)
        assert "unifi_api_key" in handler.formatter._sensitive_keys
        assert "wlan_passphrase" in handler.formatter._sensitive_keys
        assert "password" in handler.formatter._sensitive_keys

    @pytest.mark.parametrize("level_str", ["debug", "INFO", "Warning"])
    def test_case_insensitive_level(self, level_str: str) -> None:
        configure_logging(level=level_str, fmt="text")
        assert logging.getLogger().level == getattr(logging, level_str.upper())
