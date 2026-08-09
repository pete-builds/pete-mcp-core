"""Structured logging for MCP servers.

Emits JSON to stderr by default so log aggregators (Loki, Datadog, anything
that ingests JSON lines) can parse each record without regex hacks.
``fmt="text"`` falls back to a plain human-readable format for local
development.

Stderr, never stdout: the stdio MCP transport uses stdout for JSON-RPC framing;
any log line on stdout corrupts the protocol.

The formatter scrubs a small set of well-known sensitive keys defensively in
case caller code accidentally drops one into ``extra``. Callers can pass
additional sensitive-key names via ``extra_sensitive_keys``.

``configure_logging`` is idempotent by way of tagging its own handler: on
re-entry it only replaces handlers it previously installed and leaves any
other root handler (e.g. pytest's ``LogCaptureHandler``) alone. Importing a
server module from a test process therefore does not silently drop the test
runner's log capture.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

DEFAULT_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "api_key",
        "password",
        "passphrase",
        "secret",
        "token",
        "authorization",
        "x_api_key",
        "x-api-key",
        "refresh_token",
        "access_token",
        "client_secret",
        "bearer",
    }
)

_RESERVED_LOGRECORD_FIELDS: frozenset[str] = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }
)


def _scrub(value: Any, sensitive_keys: frozenset[str]) -> Any:
    """Recursively replace values under sensitive keys with ``[REDACTED]``."""
    if isinstance(value, dict):
        return {
            k: ("[REDACTED]" if k.lower() in sensitive_keys else _scrub(v, sensitive_keys))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_scrub(item, sensitive_keys) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    """Serialise each log record as a single JSON line."""

    def __init__(self, sensitive_keys: frozenset[str] = DEFAULT_SENSITIVE_KEYS) -> None:
        super().__init__()
        self._sensitive_keys = sensitive_keys

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        extras: dict[str, Any] = {}
        for key, value in record.__dict__.items():
            if key in _RESERVED_LOGRECORD_FIELDS or key.startswith("_"):
                continue
            if key.lower() in self._sensitive_keys:
                extras[key] = "[REDACTED]"
            else:
                extras[key] = _scrub(value, self._sensitive_keys)
        if extras:
            payload["extra"] = extras
        return json.dumps(payload, default=str)


_HANDLER_MARKER = "_pete_mcp_core_handler"


def configure_logging(
    level: str = "INFO",
    fmt: str = "json",
    *,
    extra_sensitive_keys: Iterable[str] | None = None,
) -> None:
    """Configure the root logger. Idempotent — safe to call multiple times.

    Only removes and replaces handlers this function previously installed
    (identified by an internal marker attribute). External handlers on the
    root logger (pytest's ``LogCaptureHandler``, an aggregator's shim, a
    caller-installed observer) are left in place.

    Args:
        level: Log level (``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``, ``CRITICAL``).
        fmt: ``json`` for one JSON line per record, ``text`` for a human format.
        extra_sensitive_keys: Additional lowercase key names whose values should
            be redacted in JSON output. Merged with :data:`DEFAULT_SENSITIVE_KEYS`.
    """
    root = logging.getLogger()
    root.setLevel(level.upper())
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            root.removeHandler(handler)

    handler = logging.StreamHandler(stream=sys.stderr)
    setattr(handler, _HANDLER_MARKER, True)
    if fmt == "json":
        keys = DEFAULT_SENSITIVE_KEYS
        if extra_sensitive_keys:
            keys = frozenset(DEFAULT_SENSITIVE_KEYS | {k.lower() for k in extra_sensitive_keys})
        handler.setFormatter(JsonFormatter(sensitive_keys=keys))
    else:
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)s %(name)s: %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S%z",
            )
        )
    root.addHandler(handler)
