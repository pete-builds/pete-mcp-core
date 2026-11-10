"""Idle-session timeout for the streamable-http transport.

Why this exists: in stateful streamable-http (the default), the MCP SDK's
``StreamableHTTPSessionManager`` keeps a transport session per client, and a
client that disconnects without ``DELETE`` leaves it behind. The SDK's
``session_idle_timeout`` reaps those, but what a server actually gets depends
on which SDK and which FastMCP it was built against. Measured, as the value a
real ``FastMCP().http_app()`` hands the manager with nothing configured:

==================  ==============  =======================================
FastMCP             MCP SDK         Idle timeout in effect
==================  ==============  =======================================
3.4.2               1.27.0          None: FastMCP passes nothing, SDK default None
3.4.2, 3.4.11       1.30.0          1800: FastMCP passes nothing, SDK default 1800
4.0.11              2.1.0, 2.3.0    None: FastMCP passes its own setting, default None
4.1.0, 4.1.7        2.3.0           1800: setting defaults to "auto", SDK default 1800
==================  ==============  =======================================

So "no timeout" is the default on an older SDK and on every FastMCP 4.0.x, and
neither the SDK nor FastMCP promises the value will hold still. This module
makes it a property of pete-mcp-core instead: it patches the SDK manager's
``__init__`` so that a manager nobody chose a timeout for gets ours, whatever
the installed pair would have done.

"Nobody chose" means one of two things. The caller did not pass
``session_idle_timeout`` at all. Or FastMCP 4.0.x passed ``None``: there the
setting is ``float | None`` with a default of ``None``, an operator has no way
to say "none" that differs from saying nothing, so ``None`` from that FastMCP
is the absence of a choice. From FastMCP 4.1 on the default is ``"auto"`` and an
explicit ``None`` is a real choice, which is respected like any other value a
caller passes.

Disabling is enforced the same way: ``MCP_SESSION_IDLE_TIMEOUT=off`` installs
an explicit ``None``, so it means no idle timeout even where the SDK would
default to 1800.

Upstream context and measurements:
``docs/audits/2026-08-13-fastmcp-session-leak-upstream.md`` in ai-cli-workspace,
`modelcontextprotocol/python-sdk#3228 <https://github.com/modelcontextprotocol/python-sdk/issues/3228>`_,
and `#2455 <https://github.com/modelcontextprotocol/python-sdk/issues/2455>`_.
This module can go once the floor is a FastMCP whose setting defaults to
``"auto"`` on an SDK that defaults to 1800, with ``MCP_SESSION_IDLE_TIMEOUT``
mapped onto FastMCP's own ``http_session_idle_timeout`` setting.

Known residual: a session terminated by an explicit ``DELETE`` still leaves its
entry in ``_server_instances`` (the SDK skips that cleanup when the transport is
already terminated). This reaper does not address that; it costs a few KB per
session rather than the ~40 KB an orphaned session holds.

Tuning: set ``MCP_SESSION_IDLE_TIMEOUT`` to a number of seconds, or to ``off``
for no idle timeout. Keep it comfortably above any SSE polling gap, since the
SDK's timeout can cancel a session while a long request is in flight
(`python-sdk#2455 <https://github.com/modelcontextprotocol/python-sdk/issues/2455>`_).
On FastMCP 4, ``FASTMCP_HTTP_SESSION_IDLE_TIMEOUT`` is FastMCP's own knob for
the same thing and wins when set, because FastMCP then passes the value itself.
"""

from __future__ import annotations

import functools
import inspect
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

#: Seconds of inactivity before a stateful session is reaped. Matches the value
#: the SDK docstring recommends for most deployments.
DEFAULT_IDLE_TIMEOUT = 1800.0

_ENV_VAR = "MCP_SESSION_IDLE_TIMEOUT"
_PATCH_FLAG = "_pete_mcp_core_idle_patch"
_PATCH_TIMEOUT = "_pete_mcp_core_idle_timeout"
_DISABLE_VALUES = {"0", "off", "none", "no", "false", "disabled"}
_FASTMCP_SETTING = "http_session_idle_timeout"
_UNSET: Any = object()


def _resolve_timeout(explicit: float | None) -> float | None:
    """Resolve the idle timeout from an explicit value or the environment.

    Returns None when sessions should have no idle timeout.
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


def _fastmcp_none_is_unset() -> bool:
    """Whether a ``None`` idle timeout from the installed FastMCP is a non-choice.

    True only where FastMCP's ``http_session_idle_timeout`` setting defaults to
    ``None`` (4.0.x). FastMCP 3.x has no such setting and passes nothing, and
    4.1+ defaults to ``"auto"``, so there a ``None`` was asked for.
    """
    try:
        import fastmcp

        field = type(fastmcp.settings).model_fields[_FASTMCP_SETTING]
    except (ImportError, AttributeError, KeyError):
        return False
    return field.default is None


def _built_by_fastmcp(manager: object) -> bool:
    return type(manager).__module__.partition(".")[0] == "fastmcp"


def enable_session_reaper(timeout_seconds: float | None = None) -> float | None:
    """Give streamable-http sessions an idle timeout the SDK will honor.

    Returns the idle timeout in seconds now applied to any session manager that
    was not given one, or None when that is "no idle timeout" (disabled, or an
    SDK too old to support one). Safe to call more than once: the first call
    decides, and later calls return what it installed, so a server that calls
    this with its own value before ``run_server`` keeps that value. Never
    overrides a caller that chose ``session_idle_timeout`` itself, and never
    applies in stateless mode, where there is nothing to reap and an older SDK
    rejects the parameter outright.

    Args:
        timeout_seconds: Idle timeout to apply. Falls back to
            ``MCP_SESSION_IDLE_TIMEOUT``, then to :data:`DEFAULT_IDLE_TIMEOUT`.
            A non-positive value means no idle timeout.
    """
    timeout = _resolve_timeout(timeout_seconds)

    try:
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    except ImportError:  # pragma: no cover - mcp is a hard dependency of fastmcp
        logger.warning("Could not import StreamableHTTPSessionManager; reaper not installed")
        return None

    original = StreamableHTTPSessionManager.__init__
    if getattr(original, _PATCH_FLAG, False):
        installed: float | None = getattr(original, _PATCH_TIMEOUT)
        return installed

    signature = inspect.signature(original)
    if "session_idle_timeout" not in signature.parameters:
        if timeout is not None:
            logger.warning(
                "Installed mcp SDK does not accept session_idle_timeout; "
                "streamable-http sessions will accumulate for the life of the process. "
                "Upgrade to mcp>=1.27 to enable the reaper."
            )
        return None

    none_is_unset = _fastmcp_none_is_unset()

    @functools.wraps(original)
    def patched(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        bound = signature.bind_partial(self, *args, **kwargs)
        passed = bound.arguments.get("session_idle_timeout", _UNSET)
        unchosen = passed is _UNSET or (
            passed is None and none_is_unset and _built_by_fastmcp(self)
        )
        # A stateless transport is torn down per request, and an older SDK
        # (measured: mcp 1.27.0 and 2.1.0) raises if one is given an idle timeout.
        stateless = bool(bound.arguments.get("stateless", False))
        if unchosen and not stateless:
            # Written through the bound arguments rather than kwargs, so a
            # positional None is replaced instead of passed twice.
            bound.arguments["session_idle_timeout"] = timeout
        return original(*bound.args, **bound.kwargs)

    patched.__dict__[_PATCH_FLAG] = True
    patched.__dict__[_PATCH_TIMEOUT] = timeout
    StreamableHTTPSessionManager.__init__ = patched  # type: ignore[method-assign]
    if timeout is None:
        logger.info(
            "Session idle timeout disabled; streamable-http sessions will persist "
            "until the client deletes them or the process exits"
        )
    else:
        logger.info("Session idle reaper enabled at %.0fs", timeout)
    return timeout
