"""Idle-session reaper for the streamable-http transport.

Why this exists: in stateful streamable-http (the default), the MCP SDK's
``StreamableHTTPSessionManager`` registers a transport session and never reaps
it. The SDK added ``session_idle_timeout`` to fix that, and its own docstring
recommends 1800 seconds, but FastMCP neither passes nor exposes the parameter,
so ``mcp.http_app(session_idle_timeout=1800)`` raises ``TypeError``. Sessions
therefore accumulate for the life of the process on every server we run.

This patches the SDK manager's ``__init__`` to supply a default when the caller
did not, which is exactly what FastMCP will do natively once
`PrefectHQ/fastmcp#3443 <https://github.com/PrefectHQ/fastmcp/pull/3443>`_
lands. Delete this module when it does.

Upstream context and measurements:
``docs/audits/2026-08-13-fastmcp-session-leak-upstream.md`` in ai-cli-workspace,
`modelcontextprotocol/python-sdk#3228 <https://github.com/modelcontextprotocol/python-sdk/issues/3228>`_,
and `#2455 <https://github.com/modelcontextprotocol/python-sdk/issues/2455>`_.

Known residual: a session terminated by an explicit ``DELETE`` still leaves its
entry in ``_server_instances`` (the SDK skips that cleanup when the transport is
already terminated). This reaper does not address that; it costs a few KB per
session rather than the ~40 KB an orphaned session holds.

Tuning: set ``MCP_SESSION_IDLE_TIMEOUT`` to a number of seconds, or to ``off``
to disable. Keep it comfortably above any SSE polling gap, since the SDK's
timeout can cancel a session while a long request is in flight
(`python-sdk#2455 <https://github.com/modelcontextprotocol/python-sdk/issues/2455>`_).
"""

from __future__ import annotations

import functools
import inspect
import logging
import os

logger = logging.getLogger(__name__)

#: Seconds of inactivity before a stateful session is reaped. Matches the value
#: the SDK docstring recommends for most deployments.
DEFAULT_IDLE_TIMEOUT = 1800.0

_ENV_VAR = "MCP_SESSION_IDLE_TIMEOUT"
_PATCH_FLAG = "_pete_mcp_core_idle_patch"
_DISABLE_VALUES = {"0", "off", "none", "no", "false", "disabled"}


def _resolve_timeout(explicit: float | None) -> float | None:
    """Resolve the idle timeout from an explicit value or the environment.

    Returns None when the reaper should stay off.
    """
    if explicit is not None:
        return explicit if explicit > 0 else None

    raw = os.getenv(_ENV_VAR)
    if raw is None or not raw.strip():
        return DEFAULT_IDLE_TIMEOUT

    value = raw.strip().lower()
    if value in _DISABLE_VALUES:
        return None
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{_ENV_VAR} must be a number of seconds or 'off', got {raw!r}") from exc
    return parsed if parsed > 0 else None


def enable_session_reaper(timeout_seconds: float | None = None) -> float | None:
    """Give streamable-http sessions an idle timeout the SDK will honor.

    Safe to call more than once; the patch is installed at most once. Never
    overrides a caller that passes ``session_idle_timeout`` itself, and never
    applies in stateless mode, where the SDK rejects the parameter outright.

    Args:
        timeout_seconds: Idle timeout to apply. Falls back to
            ``MCP_SESSION_IDLE_TIMEOUT``, then to :data:`DEFAULT_IDLE_TIMEOUT`.
            A non-positive value disables the reaper.

    Returns:
        The timeout that was installed, or None if the reaper stayed off.
    """
    timeout = _resolve_timeout(timeout_seconds)
    if timeout is None:
        logger.info(
            "Session idle reaper disabled; streamable-http sessions will persist "
            "for the life of the process"
        )
        return None

    try:
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    except ImportError:  # pragma: no cover - mcp is a hard dependency of fastmcp
        logger.warning("Could not import StreamableHTTPSessionManager; reaper not installed")
        return None

    original = StreamableHTTPSessionManager.__init__
    if getattr(original, _PATCH_FLAG, False):
        return timeout

    signature = inspect.signature(original)
    if "session_idle_timeout" not in signature.parameters:
        logger.warning(
            "Installed mcp SDK does not accept session_idle_timeout; "
            "streamable-http sessions will accumulate for the life of the process. "
            "Upgrade to mcp>=1.27 to enable the reaper."
        )
        return None

    @functools.wraps(original)
    def patched(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        bound = signature.bind_partial(self, *args, **kwargs)
        already_set = "session_idle_timeout" in bound.arguments
        # The SDK raises if a stateless manager is given an idle timeout, and a
        # stateless transport is torn down per request anyway.
        stateless = bool(bound.arguments.get("stateless", False))
        if not already_set and not stateless:
            kwargs["session_idle_timeout"] = timeout
        return original(self, *args, **kwargs)

    patched.__dict__[_PATCH_FLAG] = True
    StreamableHTTPSessionManager.__init__ = patched  # type: ignore[method-assign]
    logger.info(
        "Session idle reaper enabled at %.0fs (workaround for PrefectHQ/fastmcp#3443)",
        timeout,
    )
    return timeout
