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


class TestConfigureLogging:
    def teardown_method(self) -> None:
        root = logging.getLogger()
        for handler in list(root.handlers):
            root.removeHandler(handler)

    def test_installs_stderr_handler(self) -> None:
        configure_logging(level="INFO", fmt="json")
        root = logging.getLogger()
        assert len(root.handlers) == 1
        handler = root.handlers[0]
        assert isinstance(handler, logging.StreamHandler)
        assert handler.stream is sys.stderr

    def test_idempotent(self) -> None:
        configure_logging(level="INFO", fmt="json")
        configure_logging(level="DEBUG", fmt="text")
        root = logging.getLogger()
        assert len(root.handlers) == 1
        assert root.level == logging.DEBUG

    def test_json_format(self) -> None:
        configure_logging(level="INFO", fmt="json")
        handler = logging.getLogger().handlers[0]
        assert isinstance(handler.formatter, JsonFormatter)

    def test_text_format(self) -> None:
        configure_logging(level="INFO", fmt="text")
        handler = logging.getLogger().handlers[0]
        assert not isinstance(handler.formatter, JsonFormatter)

    def test_extra_sensitive_keys_extend(self) -> None:
        configure_logging(
            level="INFO",
            fmt="json",
            extra_sensitive_keys=["unifi_api_key", "wlan_passphrase"],
        )
        handler = logging.getLogger().handlers[0]
        assert isinstance(handler.formatter, JsonFormatter)
        assert "unifi_api_key" in handler.formatter._sensitive_keys
        assert "wlan_passphrase" in handler.formatter._sensitive_keys
        assert "password" in handler.formatter._sensitive_keys

    @pytest.mark.parametrize("level_str", ["debug", "INFO", "Warning"])
    def test_case_insensitive_level(self, level_str: str) -> None:
        configure_logging(level=level_str, fmt="text")
        assert logging.getLogger().level == getattr(logging, level_str.upper())
