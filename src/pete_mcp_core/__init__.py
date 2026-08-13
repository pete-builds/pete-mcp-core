"""pete-mcp-core: shared substrate for pete-builds MCP servers."""

from __future__ import annotations

from pete_mcp_core.auth import build_auth_provider
from pete_mcp_core.errors import format_response, tool_errors
from pete_mcp_core.healthcheck import check
from pete_mcp_core.logging_setup import JsonFormatter, configure_logging
from pete_mcp_core.serve import run_server
from pete_mcp_core.session_reaper import enable_session_reaper
from pete_mcp_core.settings import BaseCoreSettings

__version__ = "0.1.0"

__all__ = [
    "BaseCoreSettings",
    "JsonFormatter",
    "__version__",
    "build_auth_provider",
    "check",
    "configure_logging",
    "enable_session_reaper",
    "format_response",
    "run_server",
    "tool_errors",
]
