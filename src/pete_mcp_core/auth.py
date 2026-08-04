"""Bearer-token auth provider builder.

Wraps :class:`fastmcp.server.auth.providers.jwt.StaticTokenVerifier` for the
single-token case that every server needs. Returns ``None`` when no token is
configured — the caller passes that straight to ``FastMCP(auth=...)``.

Fail-closed mode: pass ``required=True`` to raise instead of returning
``None`` when no token is set. Use for streamable-http deployments where
running without auth would be a security regression.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import SecretStr

if TYPE_CHECKING:
    from fastmcp.server.auth.providers.jwt import StaticTokenVerifier


class AuthRequiredError(RuntimeError):
    """Raised when ``required=True`` but no token was provided."""


def _unwrap(token: str | SecretStr | None) -> str:
    if token is None:
        return ""
    if isinstance(token, SecretStr):
        return token.get_secret_value().strip()
    return token.strip()


def build_auth_provider(
    token: str | SecretStr | None,
    *,
    client_id: str,
    required: bool = False,
    scopes: list[str] | None = None,
    logger: logging.Logger | None = None,
) -> StaticTokenVerifier | None:
    """Build a bearer-token auth provider, or ``None`` if unset.

    Args:
        token: The bearer token. May be a raw string, a pydantic ``SecretStr``,
            or ``None``. Whitespace is stripped.
        client_id: Identifier assigned to callers presenting this token.
            Available via ``fastmcp.server.dependencies.get_access_token()``.
        required: If ``True`` and ``token`` is empty, raise
            :exc:`AuthRequiredError` instead of returning ``None``.
        scopes: OAuth-style scopes granted to this client. Optional.
        logger: Logger to warn against when auth is silently disabled.

    Returns:
        A :class:`StaticTokenVerifier` for :meth:`FastMCP.__init__`'s ``auth``
        kwarg, or ``None`` when no token is configured and ``required=False``.
    """
    from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

    unwrapped = _unwrap(token)
    if not unwrapped:
        if required:
            raise AuthRequiredError(
                f"Bearer token required for client {client_id!r} but not provided"
            )
        if logger is not None:
            logger.warning(
                "No bearer token configured; HTTP transport will accept unauthenticated requests",
                extra={"client_id": client_id},
            )
        return None
    return StaticTokenVerifier(
        tokens={unwrapped: {"client_id": client_id, "scopes": scopes or []}},
    )
