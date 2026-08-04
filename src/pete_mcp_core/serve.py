"""Transport wiring for a FastMCP server.

Replaces the ~15-line ``main()`` transport shim that every server hand-writes.
Reads ``MCP_TRANSPORT`` to pick between stdio and streamable-http; for HTTP,
falls back through ``FASTMCP_HOST`` / ``MCP_HOST`` / default and
``FASTMCP_PORT`` / ``MCP_PORT`` / ``default_port``.

Also mirrors host/port back into ``FASTMCP_HOST`` / ``FASTMCP_PORT`` before
calling ``mcp.run(...)`` so any FastMCP internal that consults those env vars
sees the resolved value.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP


def _resolve_transport(default: str) -> str:
    value = os.getenv("MCP_TRANSPORT", default).strip().lower()
    if value not in {"stdio", "streamable-http"}:
        raise ValueError(f"MCP_TRANSPORT must be 'stdio' or 'streamable-http', got {value!r}")
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
        mcp.run(transport="stdio")
        return

    host = _resolve_host(default_host)
    port = _resolve_port(default_port)
    os.environ["FASTMCP_HOST"] = host
    os.environ["FASTMCP_PORT"] = str(port)
    mcp.run(transport="streamable-http", host=host, port=port)
