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
| `pete_mcp_core.healthcheck` | `check(port, path)` and a `pete-mcp-healthcheck` CLI for Docker `HEALTHCHECK` directives. |
| `pete_mcp_core.serve` | `run_server(mcp, *, default_port)` — stdio + streamable-http switch, `FASTMCP_HOST` / `MCP_HOST` env fallback. |
| `pete_mcp_core.errors` | `@tool_errors(logger, *, catch)` decorator + shared `format_response(data)` helper. |
| `pete_mcp_core.settings` | `BaseCoreSettings` — `mcp_transport`, `mcp_host`, `mcp_port`, `log_level`, `log_format`, `auth_token`, `auth_required`. |
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
