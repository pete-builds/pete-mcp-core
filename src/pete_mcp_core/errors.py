"""Tool error envelope and response formatter.

Every server was hand-writing a ``_format`` helper that JSON-dumped tool
results and a per-tool ``try/except`` that turned exceptions into
``{"error": str(e)}``. Both live here now.
"""

from __future__ import annotations

import functools
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

T = TypeVar("T")


def format_response(data: object) -> str:
    """Serialise a tool result as an indented JSON string.

    Non-serialisable values fall back to ``str(...)`` via ``default=str`` so
    datetimes, UUIDs, and pydantic models don't blow up the tool.
    """
    return json.dumps(data, indent=2, default=str)


def tool_errors(
    logger_name: str,
    *,
    catch: type[BaseException] | tuple[type[BaseException], ...] = Exception,
    log_traceback: bool = False,
) -> Callable[[Callable[..., Awaitable[str]]], Callable[..., Awaitable[str]]]:
    """Decorator that catches exceptions and returns a JSON error envelope.

    The wrapped tool must be ``async`` and return ``str`` (the FastMCP tool
    contract). On error, returns ``format_response({"error": str(exc)})`` and
    logs at ``ERROR`` level.

    Args:
        logger_name: Logger to record errors against (typically the server name).
        catch: Exception class or tuple to catch. Defaults to ``Exception`` so
            :class:`BaseException` subclasses like ``KeyboardInterrupt`` still
            propagate.
        log_traceback: If ``True``, log with ``exc_info=True`` so the traceback
            lands in the JSON log record.

    Example::

        @mcp.tool()
        @tool_errors("myserver.tools")
        async def do_thing(x: int) -> str:
            return format_response({"result": x * 2})
    """
    logger = logging.getLogger(logger_name)

    def decorator(func: Callable[..., Awaitable[str]]) -> Callable[..., Awaitable[str]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> str:
            try:
                return await func(*args, **kwargs)
            except catch as exc:
                logger.error(
                    "tool %s failed: %s",
                    func.__name__,
                    exc,
                    exc_info=log_traceback,
                )
                return format_response({"error": str(exc)})

        return wrapper

    return decorator
