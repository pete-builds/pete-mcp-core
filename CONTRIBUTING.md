# Contributing to pete-mcp-core

This library is the shared substrate for the `pete-builds` family of MCP
servers. Servers depend on it from PyPI, so a broken release breaks every
consumer at install time. The rules below exist for that reason.

## Local setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Before you open a pull request

All four must pass. CI runs them across Python 3.11, 3.12, and 3.13.

```bash
ruff check .
ruff format --check .
mypy
pytest
```

`mypy` runs in strict mode and is not optional. This is a library other
packages import, so the public surface carries `py.typed` and consumers get
real type information from it.

## What belongs in this library

Runtime concerns that (a) more than one server needs and (b) benefit from being
versioned together: logging setup, healthcheck, transport wiring, the tool-error
decorator, the settings base, and auth provider construction.

What does not belong here: anything only one server needs. `mcp-unifi`'s audit
log, scope middleware, and dry-run substrate stay in `mcp-unifi` until a second
server actually needs them. Premature extraction costs more than duplication.

## Adding to the public surface

Anything exported from `pete_mcp_core/__init__.py` is a compatibility promise.
When you add an export:

1. Add it to `__all__`.
2. Give it a test in `tests/test_<module>.py`.
3. Keep the signature keyword-only where a future argument is plausible, so
   adding one later is not a breaking change.

## Releasing

Version lives in two places and the release workflow **fails closed** if they
disagree with the tag. PyPI filenames are immutable, so a wrong version cannot
be repaired by re-pushing; it burns the version number permanently.

1. Bump both surfaces in one commit:
   - `pyproject.toml` → `version = "X.Y.Z"`
   - `src/pete_mcp_core/__init__.py` → `__version__ = "X.Y.Z"`
2. Update `CHANGELOG.md`.
3. Merge to `main` and confirm CI is green.
4. Tag and push:
   ```bash
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```

The `Release` workflow then verifies the version surfaces against the tag,
builds an sdist and wheel, runs `twine check --strict`, installs the built
wheel into a clean venv and asserts the import reports `X.Y.Z`, attests build
provenance, publishes to PyPI, and cuts a GitHub release with the artifacts
attached.

**Bump before you tag.** A tag pointing at a commit whose version surfaces say
something else fails the release immediately, by design.

### Trusted publishing

Publishing uses PyPI trusted publishing (OIDC). There is no API token stored in
this repository. The publisher is configured on PyPI as:

| Field | Value |
|---|---|
| Owner | `pete-builds` |
| Repository | `pete-mcp-core` |
| Workflow | `release.yml` |
| Environment | `pypi` |

If publishing starts failing with an OIDC error, check that the workflow
filename, repository name, and environment name still match that configuration
exactly. Renaming any of the three breaks the trust relationship.

## Consumers

Servers currently depending on this library: `mcp-searxng`, `mcp-threatintel`,
`mcp-spotify`. A breaking change to the public surface means a major bump plus a
coordinated update across all three. Prefer additive changes.
