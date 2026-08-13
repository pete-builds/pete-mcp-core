# pete-mcp-core

Shared substrate for the `pete-builds` family of [MCP](https://modelcontextprotocol.io)
servers. Extracts the runtime patterns that every server was reimplementing:
structured JSON logging with secret scrubbing, transport wiring, healthcheck,
tool-error envelope, pydantic-settings base, and a bearer-token auth builder
over [FastMCP](https://github.com/jlowin/fastmcp).

Ships as a library, not a framework. Import what you need; nothing is
implicit; every module is under 200 lines.

## Modules

| Module | What it gives you |
|---|---|
| `pete_mcp_core.logging_setup` | `configure_logging(level, fmt)`, `JsonFormatter`, sensitive-key scrub. Stderr-only (stdio-transport safe). |
| `pete_mcp_core.healthcheck` | `check(port, path)` and a `pete-mcp-healthcheck` CLI for Docker `HEALTHCHECK` directives. Probes a session-free sentinel path, never `/mcp` — see [Healthcheck](#healthcheck). |
| `pete_mcp_core.serve` | `run_server(mcp, *, default_port)` — stdio + streamable-http switch, `FASTMCP_HOST` / `MCP_HOST` env fallback. |
| `pete_mcp_core.errors` | `@tool_errors(logger, *, catch)` decorator + shared `format_response(data)` helper. |
| `pete_mcp_core.settings` | `BaseCoreSettings` — `mcp_transport`, `mcp_host`, `mcp_port`, `log_level`, `log_format`, `auth_token`, `auth_required`. |
| `pete_mcp_core.session_reaper` | `enable_session_reaper(timeout)` gives streamable-http sessions an idle timeout the SDK will honor. Installed automatically by `run_server`; see [Session reaping](#session-reaping). |
| `pete_mcp_core.auth` | `build_auth_provider(token, *, client_id, required)` returning a FastMCP `StaticTokenVerifier` or `None`. |

## Install

```bash
pip install pete-mcp-core
```

## Minimal server

```python
from fastmcp import FastMCP
from pete_mcp_core import (
    build_auth_provider,
    configure_logging,
    format_response,
    run_server,
    tool_errors,
)
from pete_mcp_core.settings import BaseCoreSettings

settings = BaseCoreSettings()
configure_logging(settings.log_level, settings.log_format)
mcp = FastMCP(
    "MyServer",
    auth=build_auth_provider(
        settings.auth_token,
        client_id="myserver",
        required=settings.auth_required,
    ),
)


@mcp.tool()
@tool_errors(logger_name="myserver")
async def hello(name: str) -> str:
    return format_response({"greeting": f"hi, {name}"})


def main() -> None:
    run_server(mcp, default_port=3800)


if __name__ == "__main__":
    main()
```

## Healthcheck

```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=15s \
    CMD pete-mcp-healthcheck || exit 1
```

That is the whole integration. **Do not set `MCP_HEALTH_PATH=/mcp`.**

In MCP streamable-http, any request reaching the `/mcp` mount creates a
transport session before method dispatch, and nothing reaps it. Measured on a
FastMCP 3.4.4 container over 300 requests, the HTTP verb makes no difference:

| Probe | RSS growth | Per request | Sessions created |
|---|---|---|---|
| `GET /mcp` | +10.95 MiB | 38.3 KB | 300 |
| `HEAD /mcp` | +12.74 MiB | 44.5 KB | 300 |
| `OPTIONS /mcp` | +12.74 MiB | 44.5 KB | 300 |
| `GET /__pete_mcp_liveness` (default) | **+0.00 MiB** | **0 B** | **0** |

At a 30s interval, probing `/mcp` is ~2880 sessions/day ≈ 115 MiB/day ≈
**3.4 GiB/month per server**, never reclaimed.

The default `DEFAULT_HEALTH_PATH` is `/__pete_mcp_liveness`, a path no server
routes. Starlette answers 404, which proves the process is listening and its
ASGI app is routing, without touching transport state. It answers 404 under
`MCP_AUTH_REQUIRED=true` as well, so an auth-enabled server does not report
unhealthy just because the probe is unauthenticated.

| Env var | Default | Purpose |
|---|---|---|
| `FASTMCP_PORT` / `MCP_PORT` | `default_port` arg | Port. Precedence matches `serve.py`. |
| `MCP_HEALTH_PATH` | `/__pete_mcp_liveness` | Path to probe. |
| `MCP_HEALTH_CODES` | `DEFAULT_HEALTHY_CODES` | Comma-separated healthy codes, e.g. `200,503`. |

`DEFAULT_HEALTHY_CODES` is `{200, 204, 400, 401, 404, 405, 406, 503}`. A
container healthcheck answers exactly one question — "should Docker restart
this?" — so a server whose only problem is an expiring credential (503) or an
unauthenticated probe (401) must pass: a restart cannot renew a credential, it
only produces a restart loop. `500` is excluded so a genuine fault still fails.

If you point `MCP_HEALTH_PATH` at your own `@mcp.custom_route` health
endpoint, that works and is session-free too. Use `MCP_HEALTH_CODES` if the
route's status codes differ from the defaults. Servers still on
`MCP_HEALTH_PATH=/mcp` keep working, log a warning, and get best-effort
`DELETE` session reaping (measured 38.3 KB → 2.9 KB per probe, a 92% cut) —
damage control, not a fix. Unset it.

## Session reaping

In stateful streamable-http (the default), the MCP SDK registers a transport
session and never reaps it. The SDK added `session_idle_timeout` to fix that,
and its own docstring recommends 1800 seconds, but FastMCP neither passes nor
exposes it:

```python
>>> mcp.http_app(session_idle_timeout=1800)
TypeError: TransportMixin.http_app() got an unexpected keyword argument 'session_idle_timeout'
```

So sessions accumulate for the life of the process on every server. A client
that disconnects without sending `DELETE` leaks one every time.

`run_server` closes that gap by patching the SDK manager to supply a default,
which is exactly what FastMCP will do natively once
[PrefectHQ/fastmcp#3443](https://github.com/PrefectHQ/fastmcp/pull/3443) lands.
Delete `session_reaper.py` when it does.

| Env var | Default | Purpose |
|---|---|---|
| `MCP_SESSION_IDLE_TIMEOUT` | `1800` | Seconds of inactivity before a session is reaped. Set to `off` to disable. |

Verified end to end against a live FastMCP server at a 3s timeout: 25 probe
requests created 25 sessions, and `_server_instances` was back to 0 within 4s.

Two caveats. Keep the timeout comfortably above any SSE polling gap, because
the SDK's timeout can cancel a session while a request is in flight
([python-sdk#2455](https://github.com/modelcontextprotocol/python-sdk/issues/2455)).
And a session terminated by an explicit `DELETE` still leaves its registry
entry behind, which this does not address; that costs a few KB rather than the
~40 KB an orphaned session holds
([python-sdk#3228](https://github.com/modelcontextprotocol/python-sdk/issues/3228)).

## Design notes

- **What this library does not do:** wrap FastMCP. Tool registration,
  transport implementation, schema derivation, and middleware are all
  FastMCP's job. This library adds only the surrounding glue that every
  server was hand-writing.
- **What is not in v0.1:** JSONL audit log, retry-with-backoff HTTP client,
  scope middleware, bounded parameter types, dry-run / preview substrate.
  Those live in `mcp-unifi` today and will get lifted once a second server
  needs them.
- **Deliberately minimal dependencies:** `fastmcp`, `pydantic`,
  `pydantic-settings`. No httpx (servers pick their own version), no
  python-dotenv (servers call `load_dotenv()` themselves at the top of
  their module — this library never touches the environment implicitly).

## License

MIT — see [LICENSE](LICENSE).
