"""Health check for Docker HEALTHCHECK directives.

Probes a *liveness sentinel path* by default, NOT the MCP transport endpoint.

Why: in MCP streamable-http, any request that reaches the ``/mcp`` mount --
GET, HEAD or OPTIONS alike -- creates a transport session *before* method
dispatch, logged as ``Created new transport with session ID: ...``. Nothing
ever reaps those sessions. Measured on a real FastMCP 3.4.4 container, 300
requests to ``/mcp`` grew RSS by 11-13 MiB (~40 KB/request, linear) for every
one of GET/HEAD/OPTIONS, while 300 requests to a path outside the mount grew
it by 0.00 MiB and created zero sessions. A 30s Docker HEALTHCHECK is ~2880
probes/day, i.e. ~115 MiB/day or ~3.4 GiB/month of unreclaimable growth per
server. See ``DEFAULT_HEALTH_PATH``.

Modes:

- Default (``path=DEFAULT_HEALTH_PATH``): request an unrouted sentinel path.
  Starlette answers 404, which proves the process is listening and its ASGI
  app is routing, and touches no transport state. Zero server-side change
  required.
- ``path="/health"`` / ``"/healthz"``: for servers that install a dedicated
  custom route via ``@mcp.custom_route``. Expects 200 by default.
- ``path="/mcp"`` (legacy): still supported for backward compatibility, and
  still leaks. A warning is emitted and any session the probe created is
  reaped with a ``DELETE``, which measured a ~90% reduction (38 KB -> 4 KB per
  request) but not elimination. Move off it.

A container healthcheck answers one question: "should Docker restart this?"
So a server whose only problem is an expiring credential must never fail it --
a restart cannot renew a credential, it only produces a restart loop. Both the
default path (unrouted, so it cannot carry application state) and the default
code set (401 and 503 healthy, 500 not) are chosen for that property.
``MCP_HEALTH_CODES`` overrides the set when a server needs something narrower
or wider.

Environment variables read by the CLI:

- ``FASTMCP_PORT`` / ``MCP_PORT`` -- port, precedence matching
  :mod:`pete_mcp_core.serve` so the server and healthcheck never disagree.
- ``MCP_HEALTH_PATH`` -- path to probe (default ``DEFAULT_HEALTH_PATH``).
- ``MCP_HEALTH_CODES`` -- comma-separated status codes to treat as healthy,
  replacing ``DEFAULT_HEALTHY_CODES``. Unparseable or empty values fall back
  to the defaults with a warning rather than failing the container.

Callers should pass ``default_port`` matching the server's own default so a
container running without any port env var still probes the right port.
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
from collections.abc import Iterable

#: Path deliberately outside any FastMCP mount. Requesting it yields a 404
#: from Starlette, which is a liveness signal exactly as strong as the 406
#: that ``/mcp`` used to return -- both mean "the ASGI app answered" -- but
#: without creating a transport session.
DEFAULT_HEALTH_PATH = "/__pete_mcp_liveness"

#: Any of these means "the server answered", which is what a *liveness* probe
#: asks. Strict superset of the historical ``{200, 400, 405, 406}``, so no
#: setting that passed before can fail now: 404 covers the sentinel path, 406
#: the legacy ``/mcp`` probe, 200/204 a dedicated custom route, 401 a server
#: running with ``MCP_AUTH_REQUIRED=true`` (the probe is unauthenticated by
#: design), and 503 a route honestly reporting a degraded dependency or a
#: credential near expiry -- restarting cannot renew a credential, so failing
#: here would convert a warning into a restart loop.
#:
#: 500 is deliberately absent: a genuine fault must still fail the container.
DEFAULT_HEALTHY_CODES: frozenset[int] = frozenset({200, 204, 400, 401, 404, 405, 406, 503})

#: Paths that land on an MCP transport mount and therefore create a session.
TRANSPORT_PATHS: frozenset[str] = frozenset({"/mcp", "/mcp/", "/sse", "/sse/"})

_SESSION_HEADER = "mcp-session-id"


def _warn(message: str) -> None:
    print(f"pete-mcp-healthcheck: {message}", file=sys.stderr)


def _reap_session(url: str, session_id: str, timeout: float) -> None:
    """Best-effort teardown of a transport session the probe accidentally created.

    Streamable-http advertises ``Allow: GET, POST, DELETE``; a DELETE carrying
    the session id terminates it. Measured to cut the per-probe leak by ~90%.
    Failures are ignored: this is damage control, not the health signal.
    """
    request = urllib.request.Request(  # noqa: S310 - http://localhost by construction
        url, method="DELETE", headers={_SESSION_HEADER: session_id}
    )
    try:
        urllib.request.urlopen(request, timeout=timeout).close()  # noqa: S310
    except urllib.error.HTTPError as exc:
        exc.close()
    except (urllib.error.URLError, OSError):
        pass


def check(
    port: int,
    *,
    path: str = DEFAULT_HEALTH_PATH,
    healthy_codes: Iterable[int] = DEFAULT_HEALTHY_CODES,
    timeout: float = 5.0,
    host: str = "localhost",
) -> int:
    """Return 0 if healthy, 1 otherwise. Pure function for tests."""
    codes = frozenset(healthy_codes)
    url = f"http://{host}:{port}{path}"

    if path in TRANSPORT_PATHS:
        _warn(
            f"MCP_HEALTH_PATH={path!r} probes the MCP transport mount, which leaks a "
            f"transport session per probe. Unset it to use {DEFAULT_HEALTH_PATH!r}."
        )

    try:
        response = urllib.request.urlopen(url, timeout=timeout)
    except urllib.error.HTTPError as exc:
        status, headers = exc.code, exc.headers
        exc.close()
    except (urllib.error.URLError, OSError):
        return 1
    else:
        status, headers = response.status, response.headers
        response.close()

    session_id = headers.get(_SESSION_HEADER) if headers is not None else None
    if session_id:
        _warn(
            f"probe of {path!r} created transport session {session_id}; reaping it. "
            f"This path is not session-free -- probe {DEFAULT_HEALTH_PATH!r} instead."
        )
        _reap_session(url, session_id, timeout)

    return 0 if status in codes else 1


def _resolve_healthy_codes(raw: str | None) -> frozenset[int]:
    """Parse ``MCP_HEALTH_CODES``, falling back to defaults on anything odd.

    A typo must never fail the container: a restart cannot fix a bad env var,
    it only produces a restart loop.
    """
    if raw is None or not raw.strip():
        return DEFAULT_HEALTHY_CODES
    codes: set[int] = set()
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        try:
            codes.add(int(token))
        except ValueError:
            _warn(f"MCP_HEALTH_CODES has non-integer entry {token!r}; using defaults")
            return DEFAULT_HEALTHY_CODES
    if not codes:
        _warn("MCP_HEALTH_CODES parsed to an empty set; using defaults")
        return DEFAULT_HEALTHY_CODES
    return frozenset(codes)


def main(default_port: int = 3800) -> None:
    port_str = os.getenv("FASTMCP_PORT") or os.getenv("MCP_PORT") or str(default_port)
    path = os.getenv("MCP_HEALTH_PATH") or DEFAULT_HEALTH_PATH
    healthy_codes = _resolve_healthy_codes(os.getenv("MCP_HEALTH_CODES"))
    try:
        port = int(port_str)
    except ValueError:
        _warn(f"port env var is not an integer: {port_str!r}")
        sys.exit(1)
    sys.exit(check(port, path=path, healthy_codes=healthy_codes))


if __name__ == "__main__":
    main()
