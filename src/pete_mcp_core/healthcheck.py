"""Health check for Docker HEALTHCHECK directives.

Two modes:

- ``path="/mcp"`` (default): FastMCP's streamable-http transport rejects a
  bare GET with 400/405/406. Treat those as healthy — they confirm the server
  is listening and routing.
- ``path="/health"``: for servers that install a dedicated ``/health`` custom
  route via ``@mcp.custom_route``. Expects 200.

The CLI reads ``FASTMCP_PORT`` / ``MCP_PORT`` and ``MCP_HEALTH_PATH``
(defaulting to ``/mcp``) so the same Docker directive works for either style.
Precedence matches :mod:`pete_mcp_core.serve` (``FASTMCP_PORT`` wins) so the
server and the healthcheck never target different ports.

Callers should pass ``default_port`` matching the server's own default so a
container running without any port env var still probes the right port.
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
from collections.abc import Iterable

DEFAULT_HEALTHY_CODES: frozenset[int] = frozenset({200, 400, 405, 406})


def check(
    port: int,
    *,
    path: str = "/mcp",
    healthy_codes: Iterable[int] = DEFAULT_HEALTHY_CODES,
    timeout: float = 5.0,
    host: str = "localhost",
) -> int:
    """Return 0 if healthy, 1 otherwise. Pure function for tests."""
    codes = frozenset(healthy_codes)
    url = f"http://{host}:{port}{path}"
    try:
        resp = urllib.request.urlopen(url, timeout=timeout)
    except urllib.error.HTTPError as exc:
        return 0 if exc.code in codes else 1
    except (urllib.error.URLError, OSError):
        return 1
    return 0 if resp.status in codes else 1


def main(default_port: int = 3800) -> None:
    port_str = os.getenv("FASTMCP_PORT") or os.getenv("MCP_PORT") or str(default_port)
    path = os.getenv("MCP_HEALTH_PATH", "/mcp")
    try:
        port = int(port_str)
    except ValueError:
        sys.exit(1)
    sys.exit(check(port, path=path))


if __name__ == "__main__":
    main()
