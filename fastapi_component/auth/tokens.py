"""JWT access-token creation and validation.

The signing algorithm is a hardcoded constant on purpose: making it
configurable invites algorithm-confusion mistakes (e.g. accepting ``"none"``)
for no operational benefit in a shared-secret, single-issuer setup.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

_ALGORITHM = "HS256"


class InvalidAccessTokenError(Exception):
    """Raised when an access token is malformed, tampered with, or expired."""


def create_access_token(
    *,
    subject: str,
    role: str,
    scopes: Sequence[str],
    secret: str,
    ttl_minutes: int,
    now: datetime | None = None,
) -> str:
    """Create a signed access token with ``sub``/``role``/``scope`` claims.

    Args:
        subject: Stable user identifier for the ``sub`` claim.
        role: Role name embedded as the ``role`` claim.
        scopes: Scopes embedded as the ``scope`` list claim.
        secret: HS256 signing secret.
        ttl_minutes: Lifetime; ``exp`` is set this far after ``iat``.
        now: Issue time override for tests; defaults to the current UTC time.
    """
    issued_at = now if now is not None else datetime.now(timezone.utc)
    claims = {
        "sub": subject,
        "role": role,
        "scope": list(scopes),
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=ttl_minutes),
    }
    return jwt.encode(claims, secret, algorithm=_ALGORITHM)


def decode_access_token(token: str, *, secret: str) -> dict[str, Any]:
    """Validate signature and expiry, returning the token's claims.

    Raises:
        InvalidAccessTokenError: If the token is malformed, signed with the
            wrong key or algorithm, expired, or missing required claims.
    """
    try:
        return jwt.decode(
            token,
            secret,
            algorithms=[_ALGORITHM],
            options={"require": ["sub", "exp", "iat"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidAccessTokenError(str(exc)) from exc
