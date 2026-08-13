# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **Memory leak: the healthcheck no longer probes the MCP transport endpoint.**
  `healthcheck` defaulted to `GET /mcp`. In MCP streamable-http, any request
  reaching the `/mcp` mount creates a transport session *before* method
  dispatch, and nothing reaps it. Measured on a FastMCP 3.4.4 container over
  300 requests: **GET +10.95 MiB (38.3 KB/req, 300 sessions), HEAD +12.74 MiB
  (44.5 KB/req, 300 sessions), OPTIONS +12.74 MiB (44.5 KB/req, 300
  sessions)** — the verb is irrelevant. At the standard 30s `HEALTHCHECK`
  interval that is ~2880 sessions/day ≈ 115 MiB/day ≈ **3.4 GiB/month per
  server**, never reclaimed.

  `DEFAULT_HEALTH_PATH` is now `/__pete_mcp_liveness`, an unrouted sentinel
  path. Starlette answers 404, which proves the process is listening and its
  ASGI app is routing — exactly the same class of signal as the old 406 — but
  creates no session. Same container, same 300 probes through the real
  `pete-mcp-healthcheck` CLI: **+0.00 MiB, 0 B/probe, 0 sessions, 0 failed
  probes.** The sentinel also returns 404 under `MCP_AUTH_REQUIRED=true`,
  so it is immune to the 401 trap that made auth-enabled servers report
  permanently unhealthy while serving fine.

  Servers that still set `MCP_HEALTH_PATH=/mcp` keep working and now get a
  stderr warning plus best-effort session reaping via `DELETE`, measured to
  cut their leak from 38.3 KB to 2.9 KB per probe (92%). Reaping is damage
  control, not a fix — unset `MCP_HEALTH_PATH` to eliminate the leak.
- `healthcheck.main` now accepts a `default_port` argument so per-server
  shims can pass the port their server actually binds. Previously the shared
  default was hard-coded to 3800, which silently marked every server whose
  own default was different (e.g. `mcp-threatintel` on 3707) unhealthy when
  run without `FASTMCP_PORT` / `MCP_PORT` in the environment.
- `healthcheck.main` env-var precedence now matches `serve.py`: `FASTMCP_PORT`
  wins over `MCP_PORT`. Previously the two disagreed, so setting only
  `MCP_PORT` in `.env` while compose set `FASTMCP_PORT` sent the healthcheck
  probing a different port than the server bound.
- `configure_logging` no longer strips every root-logger handler on entry.
  It now tags its own handler with a marker attribute and only replaces
  handlers it previously installed, leaving external handlers (pytest's
  `LogCaptureHandler`, aggregator shims, caller-installed observers) in
  place. Importing a server module from a test process no longer wipes
  pytest's log capture.

### Added

- `MCP_HEALTH_CODES` env var: comma-separated status codes overriding
  `DEFAULT_HEALTHY_CODES` in the CLI, which previously hardcoded them. This
  is what made a `/healthz`-style route unusable as a container healthcheck —
  it could not return 503-when-degraded without risking a restart loop.
  Unparseable or empty values fall back to the defaults with a warning
  rather than failing the container, since a restart cannot fix an env var.
- `DEFAULT_HEALTHY_CODES` gains `204`, `401`, `404`, and `503`, a strict
  superset of the previous `{200, 400, 405, 406}` so nothing that passed
  before can fail now. A container healthcheck answers only "should Docker
  restart this?", and a restart can neither renew an expiring credential
  (503) nor supply a bearer token (401). `500` stays out: a genuine fault
  must still fail.
- `DEFAULT_HEALTH_PATH` and `TRANSPORT_PATHS` are exported so servers can
  assert in their own tests that they are not probing a transport mount.
- `serve._resolve_transport` logs a WARNING when `MCP_TRANSPORT` in the
  environment overrides the caller's `default_transport`. A stray
  `MCP_TRANSPORT=stdio` on an HTTP deployment previously disabled the
  listener silently; it now surfaces in `docker logs` at startup.
- `serve.run_server` logs an INFO startup banner naming the bound
  `host:port` and transport (or `stdio` for stdio deployments), so operators
  can confirm the process came up on the interface they expected.
- `build_auth_provider` logs an INFO line when a bearer-token verifier is
  built (previously only the disabled-auth case logged). SREs auditing
  `docker logs | grep -i auth` can now confirm auth is wired before opening
  the port.

## [0.1.0]

First release. Extracted from `mcp-unifi` and the three servers that had each
reimplemented a subset of the same substrate.

### Added

- `configure_logging` and `JsonFormatter`: structured JSON logging with
  sensitive-key redaction, extensible per caller.
- `check` and the `pete-mcp-healthcheck` console script: container healthcheck
  against a server's `/mcp` endpoint, treating 400/405/406 as healthy since a
  bare GET to a streamable-http endpoint is not an error.
- `run_server`: transport wiring for stdio and streamable-http, with host and
  port environment fallback.
- `tool_errors`: decorator that converts tool exceptions into a consistent
  error envelope instead of leaking tracebacks to the client.
- `format_response`: the shared response shape used by the error envelope.
- `BaseCoreSettings`: pydantic-settings base carrying `mcp_transport`,
  `mcp_host`, `mcp_port`, `log_level`, `log_format`, `auth_token`, and
  `auth_required`. Servers subclass it.
- `build_auth_provider`: bearer-token verifier construction for the
  single-token case.
- `py.typed`, so consumers get real type information.

[Unreleased]: https://github.com/pete-builds/pete-mcp-core/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/pete-builds/pete-mcp-core/releases/tag/v0.1.0
