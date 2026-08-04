"""Tests for pete_mcp_core.errors."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import pytest

from pete_mcp_core.errors import format_response, tool_errors


class TestFormatResponse:
    def test_serialises_dict(self) -> None:
        assert json.loads(format_response({"a": 1})) == {"a": 1}

    def test_indented_output(self) -> None:
        assert "\n" in format_response({"a": 1, "b": 2})

    def test_falls_back_to_str_for_non_serialisable(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        parsed = json.loads(format_response({"when": now}))
        assert parsed["when"].startswith("2026-01-01")

    def test_handles_list(self) -> None:
        assert json.loads(format_response([1, 2, 3])) == [1, 2, 3]


class TestToolErrors:
    async def test_success_passes_through(self) -> None:
        @tool_errors("test.logger")
        async def ok() -> str:
            return format_response({"result": "ok"})

        result = await ok()
        assert json.loads(result) == {"result": "ok"}

    async def test_catches_exception_by_default(self) -> None:
        @tool_errors("test.logger")
        async def boom() -> str:
            raise RuntimeError("kaboom")

        result = await boom()
        assert json.loads(result) == {"error": "kaboom"}

    async def test_custom_catch_class(self) -> None:
        @tool_errors("test.logger", catch=ValueError)
        async def bad_value() -> str:
            raise ValueError("bad")

        result = await bad_value()
        assert json.loads(result) == {"error": "bad"}

    async def test_custom_catch_lets_others_through(self) -> None:
        @tool_errors("test.logger", catch=ValueError)
        async def unrelated() -> str:
            raise RuntimeError("not caught")

        with pytest.raises(RuntimeError, match="not caught"):
            await unrelated()

    async def test_does_not_catch_base_exception(self) -> None:
        @tool_errors("test.logger")
        async def cancelled() -> str:
            raise KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            await cancelled()

    async def test_logs_error(self, caplog: pytest.LogCaptureFixture) -> None:
        @tool_errors("test.logger")
        async def failing() -> str:
            raise RuntimeError("oh no")

        with caplog.at_level(logging.ERROR, logger="test.logger"):
            await failing()

        assert any("failing" in rec.getMessage() for rec in caplog.records)
        assert any("oh no" in rec.getMessage() for rec in caplog.records)

    async def test_log_traceback_option(self, caplog: pytest.LogCaptureFixture) -> None:
        @tool_errors("test.logger", log_traceback=True)
        async def failing() -> str:
            raise RuntimeError("with trace")

        with caplog.at_level(logging.ERROR, logger="test.logger"):
            await failing()

        assert any(rec.exc_info is not None for rec in caplog.records)

    async def test_preserves_signature_and_docstring(self) -> None:
        @tool_errors("test.logger")
        async def documented(x: int, y: int = 5) -> str:
            """Add two numbers."""
            return format_response({"sum": x + y})

        assert documented.__doc__ == "Add two numbers."
        assert documented.__name__ == "documented"
        result = await documented(3, y=4)
        assert json.loads(result) == {"sum": 7}
