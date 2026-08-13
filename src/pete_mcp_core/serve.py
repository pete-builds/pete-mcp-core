"""Transport wiring for a FastMCP server.

Replaces the ~15-line ``main()`` transport shim that every server hand-writes.
Reads ``MCP_TRANSPORT`` to pick between stdio and streamable-http; for HTTP,
falls back through ``FASTMCP_HOST`` / ``MCP_HOST`` / default and
``FASTMCP_PORT`` / ``MCP_PORT`` / ``default_port``.

Also mirrors host/port back into ``FASTMCP_HOST`` / ``FASTMCP_PORT`` before
calling ``mcp.run(...)`` so any FastMCP internal that consults those env vars
sees the resolved value.

Logs a WARNING when ``MCP_TRANSPORT`` overrides the caller's default (a stray
``MCP_TRANSPORT=stdio`` on an HTTP deployment silently disables the listener
otherwise), and an INFO startup banner naming the bound host/port/transport
so operators can confirm the server came up on the interface they expected.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from pete_mcp_core.session_reaper import enable_session_reaper

if TYPE_CHECKING:
    from fastmcp import FastMCP


logger = logging.getLogger(__name__)


def _resolve_transport(default: str) -> str:
    env_value = os.getenv("MCP_TRANSPORT")
    value = default if env_value is None else env_value.strip().lower()
    if value not in {"stdio", "streamable-http"}:
        raise ValueError(f"MCP_TRANSPORT must be 'stdio' or 'streamable-http', got {value!r}")
    if env_value is not None and value != default:
        logger.warning(
            "MCP_TRANSPORT env overrode default transport %r -> %r; "
            "server may not be reachable as its deployment expects",
            default,
            value,
        )
    return value


def _resolve_host(default: str) -> str:
    return os.getenv("FASTMCP_HOST") or os.getenv("MCP_HOST") or default


def _resolve_port(default_port: int) -> int:
    raw = os.getenv("FASTMCP_PORT") or os.getenv("MCP_PORT")
    if not raw:
        return default_port
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"FASTMCP_PORT/MCP_PORT must be an integer, got {raw!r}") from exc


def run_server(
    mcp: FastMCP,
    *,
    default_port: int = 3800,
    default_transport: str = "stdio",
    default_host: str = "0.0.0.0",
) -> None:
    """Run a FastMCP server, resolving transport/host/port from env vars.

    Args:
        mcp: A FastMCP instance with tools already registered.
        default_port: Port used for streamable-http when no env var is set.
        default_transport: ``stdio`` or ``streamable-http``.
        default_host: Bind host for streamable-http when no env var is set.
    """
    transport = _resolve_transport(default_transport)
    if transport == "stdio":
        logger.info("Starting MCP server on stdio transport")
        mcp.run(transport="stdio")
        return

    host = _resolve_host(default_host)
    port = _resolve_port(default_port)
    # Stateful streamable-http sessions are never reaped without this; see
    # session_reaper for why FastMCP cannot reach the SDK's own timeout yet.
    enable_session_reaper()
    os.environ["FASTMCP_HOST"] = host
    os.environ["FASTMCP_PORT"] = str(port)
    logger.info("Starting MCP server on %s:%d (transport=streamable-http)", host, port)
    mcp.run(transport="streamable-http", host=host, port=port)
