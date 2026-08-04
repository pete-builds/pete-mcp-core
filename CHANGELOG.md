# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
